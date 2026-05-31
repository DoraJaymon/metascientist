from __future__ import annotations

import argparse
import sys
from typing import Any

from .http import MetadataApiError
from .io import write_json, write_jsonl
from .scopus import ScopusClient, extract_scopus_records
from .wos import WebOfScienceClient, extract_wos_records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect paper metadata from WoS and Scopus APIs.")
    subparsers = parser.add_subparsers(dest="provider", required=True)

    wos = subparsers.add_parser("wos", help="Use Clarivate Web of Science Starter API.")
    wos_subparsers = wos.add_subparsers(dest="action", required=True)
    wos_search = wos_subparsers.add_parser("search", help="Search Web of Science records.")
    wos_search.add_argument("--query", required=True, help='WoS query, for example TS=("machine learning").')
    wos_search.add_argument("--limit", type=int, default=10)
    wos_search.add_argument("--page", type=int, default=1)
    wos_search.add_argument("--db", default="WOS")
    wos_search.add_argument("--sort-field")
    add_output_args(wos_search)
    wos_doi = wos_subparsers.add_parser("doi", help="Search Web of Science by DOI.")
    wos_doi.add_argument("--doi", required=True)
    wos_doi.add_argument("--limit", type=int, default=5)
    wos_doi.add_argument("--db", default="WOS")
    add_output_args(wos_doi)

    scopus = subparsers.add_parser("scopus", help="Use Elsevier Scopus APIs.")
    scopus_subparsers = scopus.add_subparsers(dest="action", required=True)
    scopus_search = scopus_subparsers.add_parser("search", help="Search Scopus records.")
    scopus_search.add_argument("--query", required=True, help='Scopus query, for example TITLE-ABS-KEY("AI").')
    scopus_search.add_argument("--count", type=int, default=10)
    scopus_search.add_argument("--start", type=int, default=0)
    scopus_search.add_argument("--view", default="STANDARD")
    scopus_search.add_argument("--sort")
    add_output_args(scopus_search)
    scopus_doi = scopus_subparsers.add_parser("doi", help="Retrieve a Scopus abstract record by DOI.")
    scopus_doi.add_argument("--doi", required=True)
    scopus_doi.add_argument("--view", default="FULL")
    add_output_args(scopus_doi)

    return parser


def add_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", "-o", help="Output path. Defaults to stdout.")
    parser.add_argument("--raw", action="store_true", help="Write the raw API JSON response.")
    parser.add_argument("--format", choices=["json", "jsonl"], default="jsonl")


def write_response(response: dict[str, Any], records: list[dict[str, Any]], args: argparse.Namespace) -> None:
    if args.raw or args.format == "json":
        write_json(response, args.output)
        return
    write_jsonl(records, args.output)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.provider == "wos":
            client = WebOfScienceClient()
            if args.action == "search":
                response = client.search(
                    args.query,
                    limit=args.limit,
                    page=args.page,
                    db=args.db,
                    sort_field=args.sort_field,
                )
            elif args.action == "doi":
                response = client.get_by_doi(args.doi, limit=args.limit, db=args.db)
            else:
                parser.error(f"Unknown WoS action: {args.action}")
            write_response(response, extract_wos_records(response), args)
            return

        if args.provider == "scopus":
            client = ScopusClient()
            if args.action == "search":
                response = client.search(
                    args.query,
                    count=args.count,
                    start=args.start,
                    view=args.view,
                    sort=args.sort,
                )
                records = extract_scopus_records(response)
            elif args.action == "doi":
                response = client.get_by_doi(args.doi, view=args.view)
                records = [response]
            else:
                parser.error(f"Unknown Scopus action: {args.action}")
            write_response(response, records, args)
            return
    except (MetadataApiError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error

    parser.error(f"Unknown provider: {args.provider}")


if __name__ == "__main__":
    main()
