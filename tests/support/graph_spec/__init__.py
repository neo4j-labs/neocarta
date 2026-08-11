"""The vendored Neo4j Graph Spec (import-spec) JSON schema, pinned for S1.6 (#297).

The S1.6 mapping-mechanism verdict rests on what the Graph Spec format can and cannot
express. That is a property of the **schema**, not of prose, so the schema is vendored at
a fixed tag and asserted against — otherwise the verdict would decay silently as upstream
moves (21 release candidates and no GA at the time of writing; see ``README.md``).

Test-support only: nothing under ``neocarta/`` imports this, there is no runtime
dependency on Graph Spec, and no JVM is involved (GUIDE §6 — *"adapt behind our boundary,
don't block on it"*).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

SPEC_VERSION = "v1.0.0-rc21"
"""The upstream tag the vendored schema was taken from."""

SPEC_PATH: Path = Path(__file__).parent / "spec.v1.json"
"""The vendored ``core/src/main/resources/spec.v1.json``."""


@lru_cache(maxsize=1)
def load_spec_schema() -> dict[str, Any]:
    """Load the vendored Graph Spec JSON schema.

    Returns:
        The parsed schema document.
    """
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def spec_schema_text() -> str:
    """Read the vendored schema as raw text.

    Used for whole-document vocabulary assertions, where the point is that a keyword is
    absent from the format *entirely* rather than absent from one definition.

    Returns:
        The schema file's contents.
    """
    return SPEC_PATH.read_text(encoding="utf-8")


def definition(name: str) -> dict[str, Any]:
    """Return one ``$defs`` entry from the vendored schema.

    Args:
        name: The definition key, e.g. ``"target.entity.propertyMapping"``.

    Returns:
        The definition object.

    Raises:
        KeyError: If the definition is absent — which is itself a meaningful upstream
            change, so it surfaces rather than resolving to an empty dict.
    """
    return load_spec_schema()["$defs"][name]


__all__ = [
    "SPEC_PATH",
    "SPEC_VERSION",
    "definition",
    "load_spec_schema",
    "spec_schema_text",
]
