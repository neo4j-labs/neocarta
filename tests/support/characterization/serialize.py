"""Layer A: serialize a connector's transform-level output to a canonical dict.

The "transform-level output" is the set of node/relationship model lists a
transformer exposes as ``@property`` accessors (names ending in ``_nodes`` /
``_relationships``), plus — for transformers that have one — the ``get_properties``
allowlist that decides which columns actually reach Neo4j. This module discovers
those accessors generically, so it handles divergent transformer shapes
(``CSVTransformer`` with 9 node / 11 rel families + ``get_properties``, and
``NormalizedGraphTransformer`` with 5 / 5 and no allowlist) with no per-connector
configuration.

Determinism: node/relationship list order is *preserved* (it is deterministic
connector behavior derived from ordered inputs, so sorting would hide an ordering
regression); only dict keys are sorted, at serialization time. The ``embedding``
field is dropped — it is ``None`` at transform time today, and :func:`serialize_transform`
keeps it out of the golden so that a future change which starts populating it during
transform is caught by :func:`assert_transform_embeddings_absent` rather than silently
baking nondeterministic floats into the snapshot.
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


def _clean(dump: dict[str, Any]) -> dict[str, Any]:
    """Drop excluded (nondeterministic) keys from a model dump."""
    return {key: value for key, value in dump.items() if key not in _EXCLUDED_KEYS}


def serialize_transform(transformer: Any) -> dict[str, Any]:
    """Serialize a transformer's output to a canonical, embedding-free dict.

    Args:
        transformer: A connector transformer exposing ``*_nodes`` / ``*_relationships``
            property accessors (e.g. ``CSVTransformer`` or ``NormalizedGraphTransformer``).

    Returns:
        A dict keyed by family name (each value a list of ``model_dump(mode="json")``
        dicts in emission order). If the transformer exposes ``get_properties``, a
        ``"_properties"`` entry maps each non-empty family to its written-column
        allowlist.
    """
    families = _model_families(transformer)
    graph: dict[str, Any] = {
        family: [_clean(model.model_dump(mode="json")) for model in getattr(transformer, family)]
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


def assert_transform_embeddings_absent(transformer: Any) -> None:
    """Assert no node carries a populated ``embedding`` at transform time.

    Guards against a future refactor that starts computing embeddings inside the
    transform (which would make the golden depend on nondeterministic float vectors).

    Args:
        transformer: The transformer whose node families are checked.

    Raises:
        AssertionError: If any node's ``embedding`` is not ``None``.
    """
    for family in _model_families(transformer):
        if not family.endswith("_nodes"):
            continue
        for model in getattr(transformer, family):
            embedding = model.model_dump(mode="json").get("embedding")
            assert embedding is None, (
                f"{family}: embedding populated at transform time ({embedding!r})"
            )
