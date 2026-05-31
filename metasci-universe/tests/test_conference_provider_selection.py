from __future__ import annotations

from metasci_universe.api._providers import get_conference_provider
from metasci_universe.providers.acl_anthology import ACLAnthologyProvider
from metasci_universe.providers.cvf_openaccess import CVFOpenAccessProvider
from metasci_universe.providers.dblp_api import DblpAPIProvider
from metasci_universe.providers.openreview_api import OpenReviewAPIProvider
from metasci_universe.providers.pmlr import PMLRProvider
from metasci_universe.schemas.conferences import ConferencePapersRequest


def test_auto_conference_provider_prefers_source_specific_connectors() -> None:
    assert isinstance(get_conference_provider(ConferencePapersRequest(venue="iclr", year=2024)), OpenReviewAPIProvider)
    assert isinstance(get_conference_provider(ConferencePapersRequest(venue="acl", year=2024)), ACLAnthologyProvider)
    assert isinstance(get_conference_provider(ConferencePapersRequest(venue="cvpr", year=2024)), CVFOpenAccessProvider)
    assert isinstance(get_conference_provider(ConferencePapersRequest(venue="aistats", year=2024)), PMLRProvider)
    assert isinstance(get_conference_provider(ConferencePapersRequest(venue="sigir", year=2024)), DblpAPIProvider)


def test_source_collection_id_can_force_pmlr_auto_route() -> None:
    request = ConferencePapersRequest(venue="icml", year=2024, source_collection_id="v235")
    assert isinstance(get_conference_provider(request), PMLRProvider)
