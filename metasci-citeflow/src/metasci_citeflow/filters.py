"""Candidate filtering.

Two cut-offs, applied at different points with different values: ``filter_params_cite``
trims the mid-loop candidate pool, ``filter_params`` trims the final result set.  The
citation ceiling drops broad classics whose relevance is incidental; the year window
keeps the pool inside the period the query is about.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple


def _year(record: Any) -> Optional[int]:
    if isinstance(record, dict):
        return record.get("year") or record.get("publication_year")
    return getattr(record, "year", None)


def _citations(record: Any) -> int:
    if isinstance(record, dict):
        return record.get("citation_count") or record.get("cited_by_count") or 0
    return getattr(record, "citation_count", 0) or 0


def apply_filters(
    records: Sequence[Any],
    *,
    max_citations: Optional[int] = None,
    min_citations: Optional[int] = None,
    year_range: Optional[Tuple[Optional[int], Optional[int]]] = None,
    drop_missing_year: bool = False,
) -> Tuple[List[Any], Dict[str, int]]:
    """Return ``(kept, drop_reasons)``.

    Papers with an unknown year survive by default: the year is metadata we may simply
    not have, and dropping them would quietly penalise poorly-indexed records.
    """
    kept: List[Any] = []
    reasons = {"max_citations": 0, "min_citations": 0, "year_range": 0, "missing_year": 0}

    for record in records:
        citations = _citations(record)
        if max_citations is not None and citations > max_citations:
            reasons["max_citations"] += 1
            continue
        if min_citations is not None and citations < min_citations:
            reasons["min_citations"] += 1
            continue

        if year_range:
            year = _year(record)
            if year is None:
                if drop_missing_year:
                    reasons["missing_year"] += 1
                    continue
            else:
                low, high = year_range
                if (low is not None and year < low) or (high is not None and year > high):
                    reasons["year_range"] += 1
                    continue

        kept.append(record)

    return kept, {key: value for key, value in reasons.items() if value}
