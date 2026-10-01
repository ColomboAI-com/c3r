"""Host composition shared by imported and module-executed entrypoints."""
from dataclasses import dataclass

from .http_service import RequestFactory
from .responses import ResponsesService
from .runtime import StandaloneController
from .system_one.inference import SystemOneInference


@dataclass(frozen=True, slots=True)
class HostComponents:
    runtime: StandaloneController
    factory: RequestFactory
    system_one: SystemOneInference
    responses: ResponsesService
