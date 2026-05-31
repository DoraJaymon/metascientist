"""Clients for collecting paper metadata from subscription indexes."""

from .scopus import ScopusClient
from .wos import WebOfScienceClient

__all__ = ["ScopusClient", "WebOfScienceClient"]
