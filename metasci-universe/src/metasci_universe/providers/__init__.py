"""Provider implementations."""

from .dblp_api import DblpAPIProvider
from .openalex_api import OpenAlexAPIProvider
from .openreview_api import OpenReviewAPIProvider
from .sciencedirect_api import ScienceDirectAPIProvider
from .service import ServiceProvider
from .springer import SpringerProvider

__all__ = [
    "DblpAPIProvider",
    "OpenAlexAPIProvider",
    "OpenReviewAPIProvider",
    "ScienceDirectAPIProvider",
    "ServiceProvider",
    "SpringerProvider",
]
