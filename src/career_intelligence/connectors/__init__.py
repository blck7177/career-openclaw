"""
ATS Connectors package.

Each connector knows how to fetch job data from a specific ATS platform
using that platform's public API (where available) or best-effort HTML fetch.

Entry point for callers: connector_router.route(url, boards_registry)
"""

from .connector_router import route
from .base import NormalizedJob

__all__ = ["route", "NormalizedJob"]
