"""Session store — per-session PaperStore registry.

Each deep search session gets a UUID that keeps its PaperStore alive in memory.
Tools pass session_id between calls instead of serialising the whole store.

Sessions auto-expire after SESSION_TTL seconds of inactivity (default 2 h).
"""

from __future__ import annotations

import time
import uuid
from typing import Dict, Optional, Tuple

from metasci_universe.memory.curalib import PaperStore

SESSION_TTL = 7200  # 2 hours

_store: Dict[str, Tuple[PaperStore, float]] = {}  # {session_id: (store, last_access)}


def new_session() -> Tuple[str, PaperStore]:
    """Create a new session and return (session_id, PaperStore)."""
    sid = str(uuid.uuid4())[:8]
    store = PaperStore()
    _store[sid] = (store, time.time())
    _evict()
    return sid, store


def get_session(session_id: str) -> PaperStore:
    """Retrieve an existing PaperStore by session_id. Raises KeyError if not found."""
    if session_id not in _store:
        raise KeyError(f"Session '{session_id}' not found or expired.")
    store, _ = _store[session_id]
    _store[session_id] = (store, time.time())
    return store


def session_exists(session_id: str) -> bool:
    return session_id in _store


def _evict() -> None:
    now = time.time()
    expired = [sid for sid, (_, t) in _store.items() if now - t > SESSION_TTL]
    for sid in expired:
        del _store[sid]
