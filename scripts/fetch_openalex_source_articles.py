#!/usr/bin/env python3
"""Fetch all OpenAlex journal articles for a source and year range."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://api.openalex.org"
SELECT_FIELDS = [
    "id",
    "doi",
    "title",
    "display_name",
    "publication_year",
    "publication_date",
    "type",
    "cited_by_count",
    "open_access",
    "primary_location",
    "topics",
    "abstract_inverted_index",
    "authorships",
]


def compact_openalex_id(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("https://openalex.org/", "")
    return value


def get_json(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    request_params = {k: v for k, v in params.items() if v is not None}
    api_key = os.getenv("OPENALEX_API_KEY") or os.getenv("PYALEX_API_KEY")
    mailto = os.getenv("OPENALEX_EMAIL") or os.getenv("PYALEX_EMAIL")
    if api_key:
        request_params["api_key"] = api_key
    elif mailto:
        request_params["mailto"] = mailto

    url = f"{BASE_URL}/{endpoint.lstrip('/')}?{urlencode(request_params)}"
    req = Request(url, headers={"User-Agent": "metascientist-openalex-fetch/1.0"})
    with urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def resolve_source(name: str) -> dict[str, Any]:
    payload = get_json("/sources", {"search": name, "per_page": 5})
    results = payload.get("results") or []
    if not results:
        raise RuntimeError(f"No OpenAlex source candidates for {name!r}")
    selected = results[0]
    return {
        "input": name,
        "id": compact_openalex_id(selected.get("id")),
        "display_name": selected.get("display_name"),
        "issn_l": selected.get("issn_l"),
        "candidates": [
            {
                "id": compact_openalex_id(item.get("id")),
                "display_name": item.get("display_name"),
                "issn_l": item.get("issn_l"),
                "works_count": item.get("works_count"),
                "cited_by_count": item.get("cited_by_count"),
            }
            for item in results
        ],
    }


def normalize_authorship(authorship: dict[str, Any], index: int) -> dict[str, Any]:
    author = authorship.get("author") or {}
    return {
        "id": compact_openalex_id(author.get("id")),
        "display_name": author.get("display_name"),
        "orcid": author.get("orcid"),
        "position": index,
        "author_position": authorship.get("author_position"),
        "is_corresponding": authorship.get("is_corresponding"),
        "institutions": [
            {
                "id": compact_openalex_id(institution.get("id")),
                "display_name": institution.get("display_name"),
                "country_code": institution.get("country_code"),
                "type": institution.get("type"),
            }
            for institution in (authorship.get("institutions") or [])
        ],
    }


def normalize_work(work: dict[str, Any]) -> dict[str, Any]:
    source = ((work.get("primary_location") or {}).get("source") or {})
    normalized = {
        "id": compact_openalex_id(work.get("id")),
        "doi": work.get("doi"),
        "title": work.get("title") or work.get("display_name"),
        "publication_year": work.get("publication_year"),
        "publication_date": work.get("publication_date"),
        "type": work.get("type"),
        "cited_by_count": work.get("cited_by_count", 0),
        "is_oa": (work.get("open_access") or {}).get("is_oa"),
        "source": {
            "id": compact_openalex_id(source.get("id")),
            "name": source.get("display_name"),
            "type": source.get("type"),
            "issn_l": source.get("issn_l"),
        },
        "topics": [
            {
                "id": compact_openalex_id(topic.get("id")),
                "name": topic.get("display_name"),
                "score": topic.get("score"),
            }
            for topic in (work.get("topics") or [])[:5]
        ],
        "authors": [
            normalize_authorship(authorship, index)
            for index, authorship in enumerate(work.get("authorships") or [], start=1)
        ],
    }
    if work.get("abstract_inverted_index"):
        normalized["abstract_inverted_index"] = work["abstract_inverted_index"]
    return normalized


def fetch_all_articles(source_id: str, from_year: int, to_year: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    filters = [
        f"from_publication_date:{from_year}-01-01",
        f"to_publication_date:{to_year}-12-31",
        f"primary_location.source.id:{compact_openalex_id(source_id)}",
        "type:article",
    ]
    params = {
        "filter": ",".join(filters),
        "select": ",".join(SELECT_FIELDS),
        "sort": "publication_date:asc",
        "per_page": 100,
        "cursor": "*",
    }
    records: list[dict[str, Any]] = []
    first_meta: dict[str, Any] = {}
    last_meta: dict[str, Any] = {}
    cursor = "*"
    page = 0
    while cursor:
        params["cursor"] = cursor
        payload = get_json("/works", params)
        meta = payload.get("meta") or {}
        if not first_meta:
            first_meta = meta
        last_meta = meta
        results = payload.get("results") or []
        records.extend(results)
        page += 1
        print(f"page={page} fetched={len(results)} total={len(records)} expected={first_meta.get('count')}", flush=True)
        cursor = meta.get("next_cursor")
        if not results:
            break
        time.sleep(0.1)
    return records, {"first_meta": first_meta, "last_meta": last_meta, "filters": filters, "select": SELECT_FIELDS}


def build_qa(works: list[dict[str, Any]], metadata: dict[str, Any], source: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    year_counts = Counter(work.get("publication_year") for work in works)
    type_counts = Counter(work.get("type") for work in works)
    source_ids = Counter((work.get("source") or {}).get("id") for work in works)
    authorships = 0
    unique_authors: set[str] = set()
    unique_institutions: set[str] = set()
    author_no_inst = 0
    paper_any_no_inst = 0
    countries: Counter[str] = Counter()
    for work in works:
        any_no_inst = False
        for author in work.get("authors") or []:
            authorships += 1
            if author.get("id"):
                unique_authors.add(author["id"])
            institutions = author.get("institutions") or []
            if not institutions:
                author_no_inst += 1
                any_no_inst = True
            for institution in institutions:
                if institution.get("id"):
                    unique_institutions.add(institution["id"])
                if institution.get("country_code"):
                    countries[institution["country_code"]] += 1
        if any_no_inst:
            paper_any_no_inst += 1

    expected = (metadata.get("openalex_meta") or {}).get("count")
    return {
        "journal": source.get("display_name"),
        "source_id": source.get("id"),
        "issn_l": source.get("issn_l"),
        "year_range": metadata.get("year_range"),
        "data_file": str(output_dir / "papers.json"),
        "raw_data_file": str(output_dir / "raw_openalex_articles.json"),
        "metadata_file": str(output_dir / "metadata.json"),
        "record_count": len(works),
        "filtered_total": expected,
        "count_matches_filtered_total": len(works) == expected,
        "source_ids": dict(source_ids),
        "all_type_article": set(type_counts) == {"article"} if works else False,
        "type_counts": dict(type_counts),
        "year_counts": {str(y): year_counts.get(y, 0) for y in range(metadata["year_range"][0], metadata["year_range"][1] + 1)},
        "missing_doi": sum(1 for work in works if not work.get("doi")),
        "papers_missing_authors": sum(1 for work in works if not work.get("authors")),
        "authorships": authorships,
        "unique_authors_with_ids": len(unique_authors),
        "authorships_without_institution": author_no_inst,
        "papers_with_any_author_without_institution": paper_any_no_inst,
        "unique_institutions_with_ids": len(unique_institutions),
        "top_countries_by_authorship_institution_links": countries.most_common(20),
        "notes": [
            "Fetched by OpenAlex cursor paging without a user-set record cap; pagination stopped only when next_cursor was empty.",
            "OpenAlex filter includes type:article, so non-article records are excluded at retrieval time.",
            "Completeness is evaluated relative to OpenAlex meta.count for the exact filters.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-name")
    parser.add_argument("--source-id")
    parser.add_argument("--from-year", type=int, required=True)
    parser.add_argument("--to-year", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not args.source_name and not args.source_id:
        parser.error("Provide --source-name or --source-id")

    source = resolve_source(args.source_name) if args.source_name else {"id": compact_openalex_id(args.source_id)}
    if args.source_id:
        source["id"] = compact_openalex_id(args.source_id)
    print(json.dumps({"resolved_source": source}, ensure_ascii=False, indent=2), flush=True)

    raw_records, fetch_meta = fetch_all_articles(source["id"], args.from_year, args.to_year)
    works = [normalize_work(work) for work in raw_records]
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "provider": "openalex",
        "source": source,
        "year_range": [args.from_year, args.to_year],
        "returned_count": len(works),
        "openalex_meta": fetch_meta["first_meta"],
        "last_openalex_meta": fetch_meta["last_meta"],
        "filters": fetch_meta["filters"],
        "select": fetch_meta["select"],
    }
    (output_dir / "raw_openalex_articles.json").write_text(json.dumps(raw_records, ensure_ascii=False, indent=2))
    (output_dir / "papers.json").write_text(json.dumps(works, ensure_ascii=False, indent=2))
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
    qa = build_qa(works, metadata, source, output_dir)
    (output_dir / "qa_summary.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2))
    print(json.dumps(qa, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
