from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


USER_AGENT = "MetaDataGet-paper-metadata/0.1"


class MetadataApiError(RuntimeError):
    """Raised when a metadata API request fails."""

    def __init__(self, message: str, status: int | None = None, body: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def request_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 30.0,
    retries: int = 2,
    sleep_seconds: float = 1.0,
) -> Any:
    if params:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        separator = "&" if urllib.parse.urlparse(url).query else "?"
        url = f"{url}{separator}{query}"

    request_headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(url, headers=request_headers)
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            if error.code in {429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(sleep_seconds * (attempt + 1))
                continue
            raise MetadataApiError(
                f"API request failed with HTTP {error.code}: {url}",
                status=error.code,
                body=body,
            ) from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            if attempt < retries:
                time.sleep(sleep_seconds * (attempt + 1))
                continue

    assert last_error is not None
    raise MetadataApiError(f"API request failed: {url}") from last_error
