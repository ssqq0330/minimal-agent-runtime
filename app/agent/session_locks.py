"""Single-process locks for serializing chat turns per user and Session."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from threading import Lock, RLock
from typing import Dict, Optional, Tuple, Type


@dataclass
class _LockEntry:
    lock: RLock
    references: int = 0


class _SessionLockContext(AbstractContextManager[None]):
    def __init__(self, manager: "SessionLockManager", key: Tuple[str, str]) -> None:
        self._manager = manager
        self._key = key
        self._entry: Optional[_LockEntry] = None

    @property
    def lock(self) -> Optional[RLock]:
        """Expose the reserved lock for diagnostics after entering the context."""
        return self._entry.lock if self._entry is not None else None

    def __enter__(self) -> None:
        entry = self._manager._reserve(self._key)
        self._entry = entry
        try:
            entry.lock.acquire()
        except BaseException:
            self._manager._release_reference(self._key, entry)
            self._entry = None
            raise
        return None

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: object,
    ) -> None:
        del exc_type, exc_value, traceback
        entry = self._entry
        if entry is None:
            return None
        try:
            entry.lock.release()
        finally:
            self._manager._release_reference(self._key, entry)
            self._entry = None
        return None


class SessionLockManager:
    """Maintain independently keyed locks and discard them after the last waiter."""

    def __init__(self) -> None:
        self._manager_lock = Lock()
        self._locks: Dict[Tuple[str, str], _LockEntry] = {}

    def acquire(self, user_id: str, session_id: str) -> _SessionLockContext:
        """Return a context manager for one ``user_id + session_id`` scope."""
        return _SessionLockContext(
            self,
            (
                self._validate_key_part(user_id, "user_id"),
                self._validate_key_part(session_id, "session_id"),
            ),
        )

    @property
    def active_lock_count(self) -> int:
        """Return the number of live lock entries, primarily for diagnostics."""
        with self._manager_lock:
            return len(self._locks)

    def _reserve(self, key: Tuple[str, str]) -> _LockEntry:
        with self._manager_lock:
            entry = self._locks.get(key)
            if entry is None:
                entry = _LockEntry(RLock())
                self._locks[key] = entry
            entry.references += 1
            return entry

    def _release_reference(self, key: Tuple[str, str], entry: _LockEntry) -> None:
        with self._manager_lock:
            entry.references -= 1
            if entry.references == 0 and self._locks.get(key) is entry:
                del self._locks[key]

    @staticmethod
    def _validate_key_part(value: str, field_name: str) -> str:
        if not isinstance(value, str):
            raise ValueError("{} must be a string.".format(field_name))
        value = value.strip()
        if not value:
            raise ValueError("{} must not be empty.".format(field_name))
        return value


__all__ = ["SessionLockManager"]
