"""File-backed CiteFlow sessions.

A session owns two artifacts on disk:

``store.json``    the CuraLib ``PaperStore`` (papers + scores + discovery history)
``session.json``  the run ledger — profile, query analysis, and one row per
                  expansion round recording exactly which papers that round produced

The ledger exists because ``PaperStore.discovery_history`` cannot answer "which papers
did the *last* expansion return".  A round query over discovery history returns the
accumulated set, and the original algorithm feeds each round's seed selection from the
*newly expanded* papers only.  Keeping an explicit per-round record also makes runs
resumable and replayable across process boundaries — tool calls from a CLI each run in
their own process, so in-memory session state would not survive.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from metasci_universe.memory.curalib import PaperStore

from metasci_citeflow.profiles import CiteFlowProfile, resolve

DEFAULT_SESSION_ROOT = Path(
    os.getenv("CITEFLOW_SESSION_DIR", "metasci_outputs/citeflow/sessions")
)

_CACHE: Dict[str, "Session"] = {}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, path)


class SessionNotFoundError(KeyError):
    pass


class Session:
    """A single CiteFlow run: a paper store plus a run ledger."""

    def __init__(
        self,
        session_id: str,
        directory: Path,
        profile: CiteFlowProfile,
        store: PaperStore,
        ledger: Dict[str, Any],
    ) -> None:
        self.session_id = session_id
        self.dir = directory
        self.profile = profile
        self.store = store
        self.ledger = ledger

    # -- paths -------------------------------------------------------------

    @property
    def store_path(self) -> Path:
        return self.dir / "store.json"

    @property
    def ledger_path(self) -> Path:
        return self.dir / "session.json"

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        query: Optional[str] = None,
        profile: Optional[str] = None,
        overrides: Optional[Dict[str, Any]] = None,
        root: Optional[Path] = None,
        session_id: Optional[str] = None,
    ) -> "Session":
        resolved = resolve(profile, **(overrides or {}))
        sid = session_id or f"cf_{uuid.uuid4().hex[:10]}"
        root_dir = Path(root) if root is not None else DEFAULT_SESSION_ROOT
        directory = root_dir / sid

        ledger = {
            "session_id": sid,
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
            "query": query,
            "profile": {"name": resolved.name, "overrides": dict(overrides or {})},
            "analysis": None,
            "rounds": [],
            "judged_ids": [],
            "cocitation": {},
            "direction_diagnosis": {},
            "tool_calls": [],
        }
        session = cls(sid, directory, resolved, PaperStore(), ledger)
        session.save()
        _CACHE[sid] = session
        return session

    @classmethod
    def load(cls, session_id: str, *, root: Optional[Path] = None) -> "Session":
        root_dir = Path(root) if root is not None else DEFAULT_SESSION_ROOT
        directory = root_dir / session_id
        ledger_path = directory / "session.json"
        if not ledger_path.exists():
            raise SessionNotFoundError(f"No CiteFlow session at {ledger_path}")

        with open(ledger_path, encoding="utf-8") as handle:
            ledger = json.load(handle)

        profile_spec = ledger.get("profile") or {}
        profile = resolve(profile_spec.get("name"), **(profile_spec.get("overrides") or {}))

        store_path = directory / "store.json"
        store = PaperStore.load_from_json(str(store_path)) if store_path.exists() else PaperStore()

        session = cls(session_id, directory, profile, store, ledger)
        _CACHE[session_id] = session
        return session

    @classmethod
    def open(
        cls,
        session_id: Optional[str] = None,
        *,
        query: Optional[str] = None,
        profile: Optional[str] = None,
        overrides: Optional[Dict[str, Any]] = None,
        root: Optional[Path] = None,
    ) -> "Session":
        """Reattach to an existing session, or create a new one."""
        if session_id is None:
            return cls.create(query=query, profile=profile, overrides=overrides, root=root)
        if session_id in _CACHE:
            return _CACHE[session_id]
        return cls.load(session_id, root=root)

    def save(self) -> None:
        self.ledger["updated_at"] = _utcnow()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.store.save_to_json(str(self.store_path))
        _atomic_write_json(self.ledger_path, self.ledger)

    # -- ledger accessors --------------------------------------------------

    @property
    def analysis(self) -> Optional[Dict[str, Any]]:
        return self.ledger.get("analysis")

    def set_analysis(self, analysis: Dict[str, Any]) -> None:
        self.ledger["analysis"] = analysis
        self.save()

    @property
    def query(self) -> Optional[str]:
        return self.ledger.get("query")

    def set_query(self, query: str) -> None:
        self.ledger["query"] = query
        self.save()

    def record_round(
        self,
        *,
        round_num: int,
        phase: str,
        expanded_ids: Optional[List[str]] = None,
        new_ids: Optional[List[str]] = None,
        seed_ids: Optional[List[str]] = None,
        source_ids: Optional[List[str]] = None,
        params: Optional[Dict[str, Any]] = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        """Append one expansion record.

        ``expanded_ids`` is everything the fetch returned (including papers already in
        the store); ``new_ids`` is only what the store had not seen before.  The original
        algorithm seeds the next round from ``expanded_ids``.
        """
        row = {
            "round": round_num,
            "phase": phase,
            "at": _utcnow(),
            "seed_ids": seed_ids or [],
            "source_ids": source_ids or [],
            "expanded_ids": expanded_ids or [],
            "new_ids": new_ids or [],
            "params": params or {},
        }
        row.update(extra)
        self.ledger.setdefault("rounds", []).append(row)
        self.save()
        return row

    def rounds(self) -> List[Dict[str, Any]]:
        return list(self.ledger.get("rounds", []))

    def get_round(self, round_num: int | str, phase: Optional[str] = None) -> Optional[Dict[str, Any]]:
        rows = self.rounds()
        if phase is not None:
            rows = [r for r in rows if r.get("phase") == phase]
        if not rows:
            return None
        if round_num == "last":
            return rows[-1]
        matching = [r for r in rows if r.get("round") == round_num]
        return matching[-1] if matching else None

    def add_judged(self, paper_ids: List[str]) -> int:
        existing = set(self.ledger.get("judged_ids", []))
        added = [pid for pid in paper_ids if pid and pid not in existing]
        self.ledger.setdefault("judged_ids", []).extend(added)
        self.save()
        return len(added)

    @property
    def judged_ids(self) -> List[str]:
        return list(self.ledger.get("judged_ids", []))

    def set_cocitation(self, payload: Dict[str, Any]) -> None:
        """Persist the bulky co-citation intermediates outside the tool payload."""
        self.ledger["cocitation"] = payload
        self.save()

    @property
    def cocitation(self) -> Dict[str, Any]:
        return self.ledger.get("cocitation", {})

    def set_direction_diagnosis(self, diagnosis: Dict[str, Any]) -> None:
        """Persist the agent's direction coverage diagnosis.

        Expected structure::

            {
              "directions": {
                "unlearning": {"strength": "strong", "hub_count": 6,
                               "key_hubs": ["Machine Unlearning", ...]},
                "calibration": {"strength": "missing", "hub_count": 0},
              },
              "noise_hubs_excluded": ["Adam", "BERT"],
              "gaps_addressed": ["calibration"],
              "gaps_remaining": ["model editing"],
              "phase": "post_round1"
            }
        """
        self.ledger["direction_diagnosis"] = diagnosis
        self.save()

    @property
    def direction_diagnosis(self) -> Dict[str, Any]:
        return self.ledger.get("direction_diagnosis", {})

    def log_tool_call(self, tool: str, arguments: Dict[str, Any], summary: Dict[str, Any]) -> None:
        self.ledger.setdefault("tool_calls", []).append(
            {"tool": tool, "at": _utcnow(), "arguments": arguments, "summary": summary}
        )

    # -- reporting ---------------------------------------------------------

    def rounds_summary(self) -> List[Dict[str, Any]]:
        return [
            {
                "round": r.get("round"),
                "phase": r.get("phase"),
                "seeds": len(r.get("seed_ids", [])),
                "expanded": len(r.get("expanded_ids", [])),
                "new": len(r.get("new_ids", [])),
                "params": r.get("params", {}),
            }
            for r in self.rounds()
        ]


def clear_cache() -> None:
    """Drop in-memory sessions (used by tests to simulate a process boundary)."""
    _CACHE.clear()
