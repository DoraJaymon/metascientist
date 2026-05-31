"""Field normalization helpers for old and new MetaSci/OpenAlex records."""

from __future__ import annotations

from typing import Any


def work_id(work: dict[str, Any]) -> str:
    value = work.get("id") or work.get("work_id") or ""
    return compact_openalex_id(value)


def compact_openalex_id(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("https://openalex.org/", "")


def title(work: dict[str, Any]) -> str:
    return str(work.get("title") or work.get("display_name") or "").strip()


def year(work: dict[str, Any], field: str = "publication_year") -> int | None:
    value = work.get(field)
    if value is None and field != "publication_year":
        value = work.get("publication_year")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def citations(work: dict[str, Any]) -> int:
    try:
        return int(work.get("cited_by_count") or 0)
    except (TypeError, ValueError):
        return 0


def source(work: dict[str, Any]) -> dict[str, Any]:
    raw = work.get("source") or {}
    if not isinstance(raw, dict):
        return {}
    return {
        "id": compact_openalex_id(raw.get("id")),
        "name": raw.get("name") or raw.get("display_name") or "",
        "type": raw.get("type") or "",
        "issn_l": raw.get("issn_l") or "",
    }


def authors(work: dict[str, Any]) -> list[dict[str, Any]]:
    raw_authors = work.get("authors")
    if raw_authors is None:
        raw_authors = work.get("authorships")
    if not isinstance(raw_authors, list):
        return []

    normalized = []
    for index, item in enumerate(raw_authors, start=1):
        if not isinstance(item, dict):
            continue
        author_obj = item.get("author") if isinstance(item.get("author"), dict) else item
        normalized.append(
            {
                "id": compact_openalex_id(author_obj.get("id")),
                "name": author_obj.get("display_name") or author_obj.get("name") or "",
                "orcid": author_obj.get("orcid") or item.get("orcid"),
                "position": item.get("position") or index,
                "author_position": item.get("author_position") or "",
                "is_corresponding": item.get("is_corresponding"),
                "institutions": institutions_from_authorship(item),
            }
        )
    return normalized


def institutions_from_authorship(authorship: dict[str, Any]) -> list[dict[str, Any]]:
    raw_institutions = authorship.get("institutions") or []
    normalized = []
    for institution in raw_institutions:
        if not isinstance(institution, dict):
            continue
        normalized.append(
            {
                "id": compact_openalex_id(institution.get("id")),
                "name": institution.get("display_name") or institution.get("name") or "",
                "country_code": institution.get("country_code") or "",
                "type": institution.get("type") or "",
            }
        )
    return normalized


def topics(work: dict[str, Any]) -> list[dict[str, Any]]:
    raw_topics = work.get("topics") or work.get("concepts") or []
    normalized = []
    for topic in raw_topics:
        if not isinstance(topic, dict):
            continue
        normalized.append(
            {
                "id": compact_openalex_id(topic.get("id")),
                "name": topic.get("name") or topic.get("display_name") or "",
                "score": topic.get("score"),
            }
        )
    return normalized


def abstract_text(work: dict[str, Any]) -> str:
    direct = work.get("abstract")
    if isinstance(direct, str):
        return direct.strip()

    inverted = work.get("abstract_inverted_index")
    if not isinstance(inverted, dict):
        return ""

    positions: dict[int, str] = {}
    for token, indexes in inverted.items():
        if not isinstance(indexes, list):
            continue
        for index in indexes:
            try:
                positions[int(index)] = str(token)
            except (TypeError, ValueError):
                continue
    return " ".join(positions[index] for index in sorted(positions))


def text_for_fields(work: dict[str, Any], fields: list[str]) -> str:
    chunks: list[str] = []
    if "title" in fields:
        chunks.append(title(work))
    if "abstract" in fields:
        chunks.append(abstract_text(work))
    if "topics" in fields:
        chunks.extend(topic["name"] for topic in topics(work) if topic.get("name"))
    return " ".join(chunk for chunk in chunks if chunk).strip()


def referenced_works(work: dict[str, Any]) -> list[str]:
    refs = work.get("referenced_works") or []
    if not isinstance(refs, list):
        return []
    return [compact_openalex_id(ref) for ref in refs if ref]
