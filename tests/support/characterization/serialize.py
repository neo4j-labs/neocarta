"""Layer A: serialize a connector's transform-level output to a canonical dict.

The transform-level output is the set of node/relationship model lists a transformer
exposes as ``@property`` accessors (names ending in ``_nodes`` / ``_relationships``),
plus — for transformers that have one — the ``get_properties`` allowlist that decides
which columns actually reach Neo4j. This module discovers those accessors generically,
so it handles divergent transformer shapes (``CSVTransformer`` with its glossary/query/
tagging families + ``get_properties``, and ``NormalizedGraphTransformer`` with the
relational family and no allowlist) with no per-connector configuration.

Determinism: list order is preserved (it is deterministic connector behavior derived
from ordered inputs, so sorting would hide an ordering regression); only dict keys are
sorted, at serialization time. The ``embedding`` field is dropped — it is the known
nondeterminism source (``None`` at transform time today) and is characterized by
exclusion so a golden never depends on a vector.
"""

from __future__ import annotations

from typing import Any

_EXCLUDED_KEYS = frozenset({"embedding"})


def _model_families(transformer: Any) -> list[str]:
    """Return the transformer's node/relationship accessor names, sorted."""
    cls = type(transformer)
    return sorted(
        name
        for name in dir(cls)
        if not name.startswith("_")
        and name.endswith(("_nodes", "_relationships"))
        and isinstance(getattr(cls, name, None), property)
    )


def serialize_transform(transformer: Any) -> dict[str, Any]:
    """Serialize a transformer's output to a canonical, embedding-free dict.

    Args:
        transformer: A connector transformer exposing ``*_nodes`` / ``*_relationships``
            property accessors (e.g. ``CSVTransformer`` or ``NormalizedGraphTransformer``).

    Returns:
        A dict keyed by family name (each value a list of ``model_dump(mode="json")``
        dicts in emission order). If the transformer exposes ``get_properties``, a
        ``"_properties"`` entry maps each non-empty family to its written-column allowlist.
    """
    families = _model_families(transformer)
    graph: dict[str, Any] = {
        family: [
            {
                key: value
                for key, value in model.model_dump(mode="json").items()
                if key not in _EXCLUDED_KEYS
            }
            for model in getattr(transformer, family)
        ]
        for family in families
    }
    if hasattr(transformer, "get_properties"):
        properties = {
            family: transformer.get_properties(family)
            for family in families
            if transformer.get_properties(family)
        }
        if properties:
            graph["_properties"] = properties
    return graph
