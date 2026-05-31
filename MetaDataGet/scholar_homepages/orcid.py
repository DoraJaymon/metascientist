from __future__ import annotations

from pathlib import Path

from .http import fetch_json
from .records import HomepageRecord


ORCID_PUBLIC_API = "https://pub.orcid.org/v3.0"


def read_orcid_ids(path: str | Path) -> list[str]:
    ids: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        ids.append(normalize_orcid(value))
    return ids


def normalize_orcid(value: str) -> str:
    value = value.rstrip("/")
    if value.startswith("https://orcid.org/"):
        return value.removeprefix("https://orcid.org/")
    if value.startswith("http://orcid.org/"):
        return value.removeprefix("http://orcid.org/")
    return value


def collect_orcid_researcher_urls(orcid_ids: list[str], limit: int | None = None) -> list[HomepageRecord]:
    records: list[HomepageRecord] = []
    for raw_orcid in orcid_ids[:limit]:
        orcid_id = normalize_orcid(raw_orcid)
        profile = fetch_json(f"{ORCID_PUBLIC_API}/{orcid_id}/record")
        scholar_name = extract_name(profile) or orcid_id
        affiliation = extract_latest_affiliation(profile)

        for url_item in extract_researcher_urls(profile):
            records.append(
                HomepageRecord(
                    scholar_name=scholar_name,
                    affiliation=affiliation,
                    homepage_url=url_item["url"],
                    url_type=classify_researcher_url(url_item["url"], url_item.get("name")),
                    source="orcid",
                    source_record_id=orcid_id,
                    confidence=0.9,
                    extra={
                        "orcid": orcid_id,
                        "url_name": url_item.get("name"),
                        "visibility": url_item.get("visibility"),
                    },
                )
            )
    return records


def extract_name(profile: dict) -> str | None:
    person = profile.get("person") or {}
    name = person.get("name") or {}
    given = _value(name.get("given-names")).strip()
    family = _value(name.get("family-name")).strip()
    credit = _value(name.get("credit-name")).strip()
    full_name = " ".join(part for part in [given, family] if part).strip()
    return credit or full_name or None


def extract_latest_affiliation(profile: dict) -> str | None:
    activities = profile.get("activities-summary") or {}
    employments = ((activities.get("employments") or {}).get("affiliation-group") or [])
    candidates: list[tuple[int, str]] = []
    for group in employments:
        for summary in group.get("summaries") or []:
            employment = summary.get("employment-summary") or {}
            organization = employment.get("organization") or {}
            name = (organization.get("name") or "").strip()
            if not name:
                continue
            start_date = employment.get("start-date") or {}
            year = int(_value(start_date.get("year")) or 0)
            candidates.append((year, name))
    if not candidates:
        return None
    return sorted(candidates, reverse=True)[0][1]


def extract_researcher_urls(profile: dict) -> list[dict[str, str | None]]:
    person = profile.get("person") or {}
    urls = ((person.get("researcher-urls") or {}).get("researcher-url") or [])
    parsed: list[dict[str, str | None]] = []
    for item in urls:
        url = ((item.get("url") or {}).get("value") or "").strip()
        if not url:
            continue
        parsed.append(
            {
                "url": url,
                "name": _value(item.get("url-name")).strip() or None,
                "visibility": item.get("visibility"),
            }
        )
    return parsed


def _value(item: object) -> str:
    if isinstance(item, dict):
        return str(item.get("value") or "")
    if item is None:
        return ""
    return str(item)


def classify_researcher_url(url: str, label: str | None = None) -> str:
    value = f"{label or ''} {url}".lower()
    if "scholar.google." in value:
        return "google_scholar"
    if "dblp.org" in value:
        return "dblp"
    if "github.com" in value:
        return "github"
    if "linkedin.com" in value:
        return "social_profile"
    if "researchgate.net" in value:
        return "research_profile"
    if "homepage" in value or "personal" in value or "website" in value:
        return "personal_homepage"
    return "unknown"
