"""Fail-closed composition of a host-supplied C3R controller and HTTP ingress.

The host entrypoint owns the action catalog, measured estimates, verifier policy,
and trace sink. This module supplies no demo estimates or implicit data collection.
"""

from __future__ import annotations

import importlib
import os
import signal
import threading
from collections.abc import Callable, Mapping
from typing import Protocol, cast

from .host_components import HostComponents
from .http_service import C3RHTTPServer, RequestFactory
from .ingress_proxy import C3RIngressServer
from .internal_readiness import InternalReadinessServer
from .runtime import StandaloneController


class HostBuilder(Protocol):
    def __call__(self) -> tuple[StandaloneController, RequestFactory] | HostComponents: ...


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "")
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _port(values: Mapping[str, str], name: str, default: int) -> int:
    raw = values.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a TCP port") from error
    if not 1 <= value <= 65535:
        raise ValueError(f"{name} must be a TCP port")
    return value


def load_host_builder(reference: str) -> HostBuilder:
    """Load an explicitly configured, trusted module:function host composition."""
    module_name, separator, attribute = reference.partition(":")
    if not separator or not module_name or not attribute or not attribute.isidentifier():
        raise ValueError("C3R_HOST_ENTRYPOINT must be module:function")
    module = importlib.import_module(module_name)
    builder = getattr(module, attribute)
    if not callable(builder):
        raise ValueError("C3R_HOST_ENTRYPOINT is not callable")
    return cast(HostBuilder, builder)


def build_servers(
    values: Mapping[str, str],
    *,
    builder_loader: Callable[[str], HostBuilder] = load_host_builder,
) -> tuple[C3RHTTPServer, C3RIngressServer]:
    """Validate configuration before binding a public interface."""
    reference = _required(values, "C3R_HOST_ENTRYPOINT")
    client_token = _required(values, "C3R_CLIENT_TOKEN")
    backend_token = _required(values, "C3R_BACKEND_TOKEN")
    port = _port(values, "PORT", 8080)
    backend_port = _port(values, "C3R_BACKEND_PORT", 8081)
    ingress_host = values.get("C3R_INGRESS_HOST", "0.0.0.0")
    if ingress_host not in {"0.0.0.0", "127.0.0.1"}:
        raise ValueError("ingress host must be loopback or the TLS-host container interface")
    if port == backend_port:
        raise ValueError("ingress and backend ports must differ")
    components = builder_loader(reference)()
    if isinstance(components, HostComponents):
        runtime, factory = components.runtime, components.factory
    else:
        runtime, factory = components
    if runtime.effect_execution_enabled:
        raise ValueError("host must be recommendation-only")
    mode = values.get("C3R_MODE", "staging")
    if mode not in {"staging", "production_inference", "research_collection"}:
        raise ValueError("C3R_MODE is invalid")
    if mode == "production_inference":
        if values.get("C3R_TRACE_COLLECTION", "false").strip().lower() not in {"false", "0", "off"}:
            raise ValueError("production inference cannot collect traces")
        if values.get("C3R_ONLINE_LEARNING", "false").strip().lower() not in {"false", "0", "off"}:
            raise ValueError("production inference cannot learn online")
        if runtime.trace_persistence_enabled:
            raise ValueError("production inference requires the ephemeral trace sink")
        if not runtime.decision_enabled:
            raise ValueError("production inference requires decisions enabled")
        if not runtime.system_one_enabled:
            raise ValueError("production inference requires an enabled System-One path")
    backend = C3RHTTPServer(
        runtime=runtime,
        request_factory=factory,
        bearer_token=backend_token,
        port=backend_port,
        system_one=components.system_one if isinstance(components, HostComponents) else None,
        responses=components.responses if isinstance(components, HostComponents) else None,
        internal_readiness=components.internal_readiness if isinstance(components, HostComponents) else None,
    )
    try:
        ingress = C3RIngressServer(
            upstream_port=backend.server_port,
            client_token=client_token,
            upstream_token=backend_token,
            port=port,
            host=ingress_host,
            upstream_timeout_seconds=65 if mode == "production_inference" else 5,
        )
    except BaseException:
        backend.server_close()
        raise
    return backend, ingress


def build_internal_server(values: Mapping[str, str],
                          backend: C3RHTTPServer) -> InternalReadinessServer | None:
    """Opt-in separate maintenance binding; never forwarded by the public gateway."""
    enabled = "C3R_INTERNAL_READY_PORT" in values or "C3R_INTERNAL_READY_TOKEN" in values
    if not enabled:
        return None
    token = _required(values, "C3R_INTERNAL_READY_TOKEN")
    _required(values, "C3R_INTERNAL_READY_PORT")
    port = _port(values, "C3R_INTERNAL_READY_PORT", 8091)
    if (port in {backend.server_port, _port(values, "PORT", 8080)}
            or token in {_required(values, "C3R_CLIENT_TOKEN"),
                         _required(values, "C3R_BACKEND_TOKEN")}):
        raise ValueError("internal readiness must use a separate port and token")
    return InternalReadinessServer(token=token, port=port, probe=backend.internal_readiness)


def main() -> None:
    backend, ingress = build_servers(os.environ)
    try:
        internal = build_internal_server(os.environ, backend)
    except BaseException:
        ingress.server_close()
        backend.server_close()
        raise
    stop = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
    ingress_thread = threading.Thread(target=ingress.serve_forever, daemon=True)
    backend_started = False
    ingress_started = False
    internal_thread = (threading.Thread(target=internal.serve_forever, daemon=True)
                       if internal is not None else None)
    internal_started = False
    try:
        backend_thread.start()
        backend_started = True
        ingress_thread.start()
        ingress_started = True
        if internal_thread is not None:
            internal_thread.start()
            internal_started = True
        stop.wait()
    finally:
        if internal_started and internal is not None:
            internal.shutdown()
        if ingress_started:
            ingress.shutdown()
        if backend_started:
            backend.shutdown()
        ingress.server_close()
        backend.server_close()
        if internal is not None:
            internal.server_close()
        if internal_started and internal_thread is not None:
            internal_thread.join(timeout=5)
        if ingress_started:
            ingress_thread.join(timeout=5)
        if backend_started:
            backend_thread.join(timeout=5)


if __name__ == "__main__":
    main()

