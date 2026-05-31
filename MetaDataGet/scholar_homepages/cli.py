from __future__ import annotations

import argparse

from .csrankings import CSRANKINGS_FACULTY_URL, collect_csrankings_homepages
from .io import write_records
from .orcid import collect_orcid_researcher_urls, read_orcid_ids


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect scholar homepage URL candidates.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    csrankings = subparsers.add_parser("csrankings", help="Collect homepages from CSRankings.")
    csrankings.add_argument("--source-url", default=CSRANKINGS_FACULTY_URL)
    csrankings.add_argument("--local-csv", help="Use a local CSRankings CSV instead of downloading.")
    csrankings.add_argument("--limit", type=int)
    add_output_args(csrankings)

    orcid = subparsers.add_parser("orcid", help="Collect researcher URLs from ORCID records.")
    orcid_source = orcid.add_mutually_exclusive_group(required=True)
    orcid_source.add_argument("--orcid-file", help="Text file with one ORCID iD per line.")
    orcid_source.add_argument("--orcid-id", action="append", help="ORCID iD. Can be repeated.")
    orcid.add_argument("--limit", type=int, help="Maximum number of ORCID records to query.")
    add_output_args(orcid)

    return parser


def add_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", "-o", help="Output path. Defaults to stdout.")
    parser.add_argument("--format", choices=["jsonl", "csv"], default="jsonl")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "csrankings":
        records = collect_csrankings_homepages(
            source_url=args.source_url,
            local_path=args.local_csv,
            limit=args.limit,
        )
        write_records(records, args.output, args.format)
        return

    if args.command == "orcid":
        orcid_ids = read_orcid_ids(args.orcid_file) if args.orcid_file else args.orcid_id
        records = collect_orcid_researcher_urls(orcid_ids, limit=args.limit)
        write_records(records, args.output, args.format)
        return

    parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
