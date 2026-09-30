"""Coalesced bounded-TTL health checks; retain only a boolean and expiry."""
from collections.abc import Callable
from threading import Lock
from time import monotonic


class CachedReadiness:
    def __init__(self, probe: Callable[[], bool], *, ttl_seconds: float = 15,
                 clock: Callable[[], float] = monotonic) -> None:
        if not 0 < ttl_seconds <= 30:
            raise ValueError("readiness TTL must be between zero and 30 seconds")
        self._probe, self._ttl, self._clock = probe, ttl_seconds, clock
        self._lock = Lock()
        self._value = False
        self._expires = float("-inf")

    def __call__(self) -> bool:
        with self._lock:
            if self._clock() < self._expires:
                return self._value
            try:
                self._value = bool(self._probe())
            except (OSError, RuntimeError, ValueError, TypeError, KeyError):
                self._value = False
            self._expires = self._clock() + self._ttl
            return self._value
