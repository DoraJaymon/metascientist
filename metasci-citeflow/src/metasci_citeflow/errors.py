"""CiteFlow error types."""

from __future__ import annotations


class CiteFlowError(Exception):
    """Base class for CiteFlow failures."""


class ProviderUnavailable(CiteFlowError):
    """A data provider could not be reached or exhausted its retry budget.

    Raised rather than returning an empty list so callers can distinguish "this provider
    is down" from "this query genuinely has no results" — the first should trigger a
    fallback, the second should not.
    """


class S2Unavailable(ProviderUnavailable):
    """Semantic Scholar rejected the request after all retries (usually rate limiting).

    The public S2 pool is shared and aggressively throttled; set ``S2_API_KEY`` for a
    dedicated quota. CiteFlow falls back to OpenAlex keyword search when this is raised.
    """
