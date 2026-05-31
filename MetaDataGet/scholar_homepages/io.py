from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Iterable

from .records import HomepageRecord


CSV_FIELDS = [
    "scholar_name",
    "affiliation",
    "homepage_url",
    "url_type",
    "source",
    "source_record_id",
    "confidence",
    "collected_at",
    "extra",
]


def write_jsonl(records: Iterable[HomepageRecord], path: str | Path | None) -> None:
    handle = open(path, "w", encoding="utf-8") if path else sys.stdout
    try:
        for record in records:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
    finally:
        if path:
            handle.close()


def write_csv(records: Iterable[HomepageRecord], path: str | Path | None) -> None:
    handle = open(path, "w", encoding="utf-8", newline="") if path else sys.stdout
    try:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for record in records:
            row = record.to_dict()
            row["extra"] = json.dumps(row["extra"], ensure_ascii=False, sort_keys=True)
            writer.writerow(row)
    finally:
        if path:
            handle.close()


def write_records(records: Iterable[HomepageRecord], path: str | Path | None, output_format: str) -> None:
    if output_format == "jsonl":
        write_jsonl(records, path)
        return
    if output_format == "csv":
        write_csv(records, path)
        return
    raise ValueError(f"Unsupported output format: {output_format}")

