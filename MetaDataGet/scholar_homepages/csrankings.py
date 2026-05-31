from __future__ import annotations

import csv
import io
from pathlib import Path
from urllib.parse import urlparse

from .http import fetch_text
from .records import HomepageRecord


CSRANKINGS_FACULTY_URL = "https://raw.githubusercontent.com/emeryberger/CSrankings/gh-pages/csrankings.csv"


def collect_csrankings_homepages(
    source_url: str = CSRANKINGS_FACULTY_URL,
    local_path: str | Path | None = None,
    limit: int | None = None,
) -> list[HomepageRecord]:
    text = Path(local_path).read_text(encoding="utf-8-sig") if local_path else fetch_text(source_url)
    records: list[HomepageRecord] = []
    reader = csv.DictReader(io.StringIO(text))

    for row in reader:
        homepage_url = (row.get("homepage") or "").strip()
        scholar_name = (row.get("name") or "").strip()
        affiliation = (row.get("affiliation") or "").strip() or None
        if not homepage_url or not scholar_name:
            continue

        records.append(
            HomepageRecord(
                scholar_name=scholar_name,
                affiliation=affiliation,
                homepage_url=homepage_url,
                url_type=guess_url_type(homepage_url),
                source="csrankings",
                source_record_id=f"{scholar_name}|{affiliation or ''}",
                confidence=0.95,
                extra={
                    "scholar_id": (row.get("scholarid") or "").strip() or None,
                    "dblp_name": (row.get("dblp") or "").strip() or None,
                    "source_url": source_url if not local_path else str(local_path),
                },
            )
        )
        if limit and len(records) >= limit:
            break

    return records


def guess_url_type(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "scholar.google." in host:
        return "google_scholar"
    if "dblp.org" in host:
        return "dblp"
    if "github.com" in host or "github.io" in host:
        return "personal_homepage"
    if ".edu" in host or ".ac." in host:
        return "personal_homepage"
    return "personal_homepage"

