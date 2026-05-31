from __future__ import annotations

import pytest

from metasci_universe.api._providers import get_provider
from metasci_universe.providers.service import ServiceProvider


def test_get_provider_supports_service() -> None:
    provider = get_provider("service", service_endpoint="https://service.example/v1")
    assert isinstance(provider, ServiceProvider)


def test_service_provider_requires_endpoint() -> None:
    with pytest.raises(ValueError):
        ServiceProvider(endpoint="")
