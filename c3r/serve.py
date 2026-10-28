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

from .http_service import C3RHTTPServer, RequestFactory
from .ingress_proxy import C3RIngressServer
from .runtime import StandaloneController


class HostBuilder(Protocol):
    def __call__(self) -> tuple[StandaloneController, RequestFactory]: ...


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
    if port == backend_port:
        raise ValueError("ingress and backend ports must differ")
    runtime, factory = builder_loader(reference)()
    if runtime.effect_execution_enabled:
        raise ValueError("host must be recommendation-only")
    backend = C3RHTTPServer(
        runtime=runtime,
        request_factory=factory,
        bearer_token=backend_token,
        port=backend_port,
    )
    try:
        ingress = C3RIngressServer(
            upstream_port=backend.server_port,
            client_token=client_token,
            upstream_token=backend_token,
            port=port,
        )
    except BaseException:
        backend.server_close()
        raise
    return backend, ingress


def main() -> None:
    backend, ingress = build_servers(os.environ)
    stop = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
    ingress_thread = threading.Thread(target=ingress.serve_forever, daemon=True)
    backend_started = False
    ingress_started = False
    try:
        backend_thread.start()
        backend_started = True
        ingress_thread.start()
        ingress_started = True
        stop.wait()
    finally:
        if ingress_started:
            ingress.shutdown()
        if backend_started:
            backend.shutdown()
        ingress.server_close()
        backend.server_close()
        if ingress_started:
            ingress_thread.join(timeout=5)
        if backend_started:
            backend_thread.join(timeout=5)


if __name__ == "__main__":
    main()

