from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class HomepageRecord:
    scholar_name: str
    homepage_url: str
    source: str
    affiliation: str | None = None
    url_type: str = "unknown"
    source_record_id: str | None = None
    confidence: float = 0.8
    collected_at: str = field(default_factory=utc_now_iso)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

