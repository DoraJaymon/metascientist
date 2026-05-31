from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterable


def write_json(data: Any, path: str | Path | None) -> None:
    handle = open(path, "w", encoding="utf-8") if path else sys.stdout
    try:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    finally:
        if path:
            handle.close()


def write_jsonl(records: Iterable[dict[str, Any]], path: str | Path | None) -> None:
    handle = open(path, "w", encoding="utf-8") if path else sys.stdout
    try:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    finally:
        if path:
            handle.close()
