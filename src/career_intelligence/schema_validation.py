"""
Runtime JSON-Schema validation against the repo-root ``schemas/`` directory.

A single entry point so the search-side contracts in ``schemas/`` are actually
enforced at runtime instead of being documentation that silently drifts from
the code (e.g. ``search_query.schema.json`` was previously unused). Schemas are
loaded from ``get_repo_root()/schemas`` and cached.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import jsonschema

from .app_state.workspace_paths import get_repo_root


@lru_cache(maxsize=None)
def _load_schema(schema_name: str) -> dict[str, Any]:
    path = get_repo_root() / "schemas" / schema_name
    return json.loads(path.read_text(encoding="utf-8"))


def validate_against_schema(instance: Any, schema_name: str) -> list[str]:
    """
    Validate ``instance`` against ``schemas/<schema_name>``.

    Returns a list of human-readable error strings (empty list == valid), so
    callers can surface a clean message rather than raising.
    """
    schema = _load_schema(schema_name)
    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    return [
        f"{'.'.join(str(p) for p in e.path) or 'root'}: {e.message}"
        for e in errors
    ]
