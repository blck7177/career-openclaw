"""
URL utilities — shared so the search and research provenance gates use the
identical normalisation/hashing and cannot drift apart.
"""

from __future__ import annotations

import hashlib


def url_hash(url: str) -> str:
    """Stable short hash of a URL (md5[:8]). Used for dedup and provenance."""
    return hashlib.md5(url.encode()).hexdigest()[:8]
