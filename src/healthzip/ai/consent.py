"""Revocable in-memory grants for a browser session's optional model requests."""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Callable
from uuid import uuid4

NetworkPermission = bool | Callable[[], bool]


def network_allowed(permission: NetworkPermission) -> bool:
    """Check at the send boundary; a failed dynamic check denies the request."""
    try:
        return bool(permission() if callable(permission) else permission)
    except Exception:
        return False


class NetworkConsent:
    """UI callbacks mutate this object; workers only use immutable grants.

    A later reauthorization never revives work created before a withdrawal.
    No worker needs access to Streamlit's thread-local session state.
    """

    def __init__(self, allowed: bool = False):
        self._lock = Lock()
        self._identity = uuid4().hex
        self._generation = 0
        self._allowed = bool(allowed)

    def set_allowed(self, allowed: bool) -> None:
        with self._lock:
            if self._allowed != bool(allowed):
                self._generation += 1
                self._allowed = bool(allowed)

    def grant(self) -> ConsentGrant:
        with self._lock:
            return ConsentGrant(self, self._identity, self._generation)

    def _allows(self, generation: int) -> bool:
        with self._lock:
            return self._allowed and generation == self._generation


@dataclass(frozen=True)
class ConsentGrant:
    _owner: NetworkConsent
    session_id: str
    generation: int

    @property
    def identity(self) -> tuple[str, int]:
        return self.session_id, self.generation

    def __call__(self) -> bool:
        return self._owner._allows(self.generation)
