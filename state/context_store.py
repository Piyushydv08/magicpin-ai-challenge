"""
state/context_store.py
----------------------
Version-aware in-memory context store.

Rules (from challenge-testing-brief.md §2.1):
  - Idempotent by (context_id, version):
      same (context_id, version) → no-op, returns accepted=True.
  - Lower-or-equal version than what's stored (i.e., cur_version >= incoming):
      EXCEPT same version which is idempotent → returns accepted=False, reason=stale_version.
  - Higher version → atomically replaces old.
  - get(scope, context_id) → latest payload dict or None.
  - counts() → {"category": N, "merchant": N, "customer": N, "trigger": N}.

Thread safety: the store uses a plain dict because the judge calls endpoints
sequentially in the test window. If you move to async with true concurrency,
wrap mutations in an asyncio.Lock.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from models.schemas import VALID_SCOPES


@dataclass
class _Entry:
    version: int
    payload: Dict[str, Any]


@dataclass
class UpsertResult:
    """Return value of ContextStore.upsert()."""
    accepted: bool
    reason: Optional[str] = None          # "stale_version" | "invalid_scope" | None
    current_version: Optional[int] = None  # populated when accepted=False


class ContextStore:
    """
    Thread-safe, version-aware in-memory store for all four context scopes.

    Internal shape:
        _store: dict[(scope, context_id), _Entry]

    Invariant: for a given (scope, context_id), only the highest-version
    payload is kept. Lower versions are discarded on upsert.
    """

    def __init__(self) -> None:
        # Keys: (scope: str, context_id: str) → _Entry
        self._store: Dict[Tuple[str, str], _Entry] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upsert(
        self,
        scope: str,
        context_id: str,
        version: int,
        payload: Dict[str, Any],
    ) -> UpsertResult:
        """
        Store or update a context entry.

        Returns:
            UpsertResult(accepted=True)           – new entry or same-version idempotent hit
            UpsertResult(accepted=True)           – higher version, replaced successfully
            UpsertResult(accepted=False, ...)     – stale (cur_version > incoming version)
            UpsertResult(accepted=False, ...)     – invalid scope
        """
        if scope not in VALID_SCOPES:
            return UpsertResult(
                accepted=False,
                reason="invalid_scope",
                current_version=None,
            )

        key = (scope, context_id)

        with self._lock:
            existing = self._store.get(key)

            # --- No existing entry: always accept
            if existing is None:
                self._store[key] = _Entry(version=version, payload=payload)
                return UpsertResult(accepted=True, current_version=version)

            cur_version = existing.version

            # --- Same version: idempotent no-op (accepted=True per spec)
            if version == cur_version:
                return UpsertResult(accepted=True, current_version=cur_version)

            # --- Stale version: reject
            if version < cur_version:
                return UpsertResult(
                    accepted=False,
                    reason="stale_version",
                    current_version=cur_version,
                )

            # --- Higher version: atomically replace
            self._store[key] = _Entry(version=version, payload=payload)
            return UpsertResult(accepted=True, current_version=version)

    def get(self, scope: str, context_id: str) -> Optional[Dict[str, Any]]:
        """Return the latest payload for (scope, context_id), or None."""
        key = (scope, context_id)
        with self._lock:
            entry = self._store.get(key)
            return entry.payload if entry is not None else None

    def get_version(self, scope: str, context_id: str) -> Optional[int]:
        """Return the stored version for (scope, context_id), or None."""
        key = (scope, context_id)
        with self._lock:
            entry = self._store.get(key)
            return entry.version if entry is not None else None

    def get_all(self, scope: str) -> Dict[str, Dict[str, Any]]:
        """Return all payloads for a given scope as {context_id: payload}."""
        with self._lock:
            return {
                cid: entry.payload
                for (s, cid), entry in self._store.items()
                if s == scope
            }

    def counts(self) -> Dict[str, int]:
        """Return the number of stored entries per scope, for /v1/healthz."""
        counts: Dict[str, int] = {s: 0 for s in VALID_SCOPES}
        with self._lock:
            for (scope, _) in self._store:
                if scope in counts:
                    counts[scope] += 1
        return counts

    def clear(self) -> None:
        """Wipe all stored contexts (useful for teardown or test isolation)."""
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
