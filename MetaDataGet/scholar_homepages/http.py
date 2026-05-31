from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any


USER_AGENT = "MetaDataGet-scholar-homepage-collector/0.1"


def fetch_text(
    url: str,
    timeout: float = 30.0,
    retries: int = 2,
    sleep_seconds: float = 1.0,
    headers: dict[str, str] | None = None,
) -> str:
    data = fetch_bytes(url, timeout=timeout, retries=retries, sleep_seconds=sleep_seconds, headers=headers)
    return data.decode("utf-8-sig")


def fetch_json(url: str, timeout: float = 30.0, retries: int = 2, sleep_seconds: float = 1.0) -> Any:
    text = fetch_text(
        url,
        timeout=timeout,
        retries=retries,
        sleep_seconds=sleep_seconds,
        headers={"Accept": "application/json"},
    )
    return json.loads(text)


def fetch_bytes(
    url: str,
    timeout: float = 30.0,
    retries: int = 2,
    sleep_seconds: float = 1.0,
    headers: dict[str, str] | None = None,
) -> bytes:
    request_headers = {"User-Agent": USER_AGENT}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as error:
            last_error = error
            if attempt < retries:
                time.sleep(sleep_seconds * (attempt + 1))
    assert last_error is not None
    raise last_error
