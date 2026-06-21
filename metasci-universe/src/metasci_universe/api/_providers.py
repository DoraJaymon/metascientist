"""Provider selection helpers."""

from __future__ import annotations

from metasci_universe.providers.base import ConferencePapersProvider, MetaSciProvider
from metasci_universe.providers.acl_anthology import ACL_VENUES, ACLAnthologyProvider
from metasci_universe.providers.cvf_openaccess import CVF_VENUES, CVFOpenAccessProvider
from metasci_universe.providers.dblp_api import DblpAPIProvider
from metasci_universe.providers.openalex_api import OpenAlexAPIProvider
from metasci_universe.providers.openreview_api import OPENREVIEW_VENUE_PATTERNS, OpenReviewAPIProvider
from metasci_universe.providers.pmlr import PMLR_VENUES, PMLRProvider
from metasci_universe.providers.sciencedirect_api import ScienceDirectAPIProvider
from metasci_universe.providers.service import ServiceProvider
from metasci_universe.providers.springer import SpringerProvider
from metasci_universe.schemas.conferences import ConferencePapersRequest


def get_provider(
    provider: str = "auto",
    *,
    service_endpoint: str | None = None,
    service_token: str | None = None,
) -> MetaSciProvider:
    """Return the configured provider for Phase 1."""
    if provider in {"auto", "openalex"}:
        return OpenAlexAPIProvider()
    if provider == "sciencedirect":
        return ScienceDirectAPIProvider()
    if provider == "springer":
        return SpringerProvider()
    if provider == "service":
        return ServiceProvider(endpoint=service_endpoint, token=service_token)
    raise ValueError(f"Unsupported provider: {provider}")


def get_conference_provider(request: ConferencePapersRequest) -> ConferencePapersProvider:
    """Return a provider for conference-paper retrieval."""
    source = request.source
    if source == "auto":
        source = _auto_conference_source(request)

    if source == "openreview":
        return OpenReviewAPIProvider()
    if source == "dblp":
        return DblpAPIProvider()
    if source == "acl":
        return ACLAnthologyProvider()
    if source == "cvf":
        return CVFOpenAccessProvider()
    if source == "pmlr":
        return PMLRProvider()
    raise ValueError(f"Unsupported conference source: {source}")


def _auto_conference_source(request: ConferencePapersRequest) -> str:
    collection = (request.source_collection_id or "").casefold()
    if collection:
        if "proceedings.mlr.press" in collection or collection.startswith("v"):
            return "pmlr"
        if "openaccess.thecvf.com" in collection or collection.startswith(("cvpr", "iccv", "wacv")):
            return "cvf"
        if "aclanthology.org" in collection or _looks_like_acl_collection(collection):
            return "acl"

    if request.openreview_venue_id or request.venue in OPENREVIEW_VENUE_PATTERNS:
        return "openreview"
    if request.venue in ACL_VENUES:
        return "acl"
    if request.venue in CVF_VENUES:
        return "cvf"
    if request.venue in PMLR_VENUES:
        return "pmlr"
    return "dblp"


def _looks_like_acl_collection(value: str) -> bool:
    return len(value) >= 5 and value[:4].isdigit() and value[4] in {".", "-"}
