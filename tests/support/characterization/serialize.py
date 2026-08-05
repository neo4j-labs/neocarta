"""Layer A: serialize a connector's transform-level output to a canonical dict.

The transform-level output is the set of node/relationship model lists a transformer
exposes (names ending in ``_nodes`` / ``_relationships``), plus — for transformers that have
one — the ``get_properties`` allowlist that decides which columns actually reach Neo4j. This
module discovers those families generically, so it handles divergent transformer shapes
(``CSVTransformer`` with its glossary/query/tagging families + ``get_properties``, and
``RdbmsSchemaTransformer`` with the relational family and no allowlist) with no per-connector
configuration.

Determinism: list order is preserved (it is deterministic connector behavior derived
from ordered inputs, so sorting would hide an ordering regression); only dict keys are
sorted, at serialization time. The ``embedding`` field is dropped — it is the known
nondeterminism source (``None`` at transform time today) and is characterized by
exclusion so a golden never depends on a vector.
"""

from __future__ import annotations

from typing import Any

_EXCLUDED_KEYS = frozenset({"embedding"})
_FAMILY_SUFFIXES = ("_nodes", "_relationships")


def _model_families(transformer: Any) -> list[str]:
    """Return the transformer's node/relationship family accessor names, sorted.

    Discovers **both** conventions in use across the connectors, because the two are equally
    common and a serializer that saw only one would silently emit an empty golden:

    - ``@property`` accessors backed by a cache (BigQuery, CSV, JDBC, query-log, and the
      shared RDBMS base);
    - plain list attributes assigned in ``__init__`` (Unity Catalog, both Dataplex connectors,
      Databricks tags).

    Before S1.6 (#297) only the first was found, so ``serialize_transform`` returned ``{}`` for
    four of the nine tabular transformers. An empty dict compares equal to an empty golden, so
    the failure mode was a characterization test that passed while guarding nothing — the
    reason the reference pattern pairs every golden with an injected-change control.

    Args:
        transformer: Any connector transformer.

    Returns:
        The family accessor names, sorted.
    """
    cls = type(transformer)
    class_level = {
        name
        for name in dir(cls)
        if not name.startswith("_")
        and name.endswith(_FAMILY_SUFFIXES)
        and isinstance(getattr(cls, name, None), property)
    }
    instance_level = {
        name
        for name, value in vars(transformer).items()
        if not name.startswith("_") and name.endswith(_FAMILY_SUFFIXES) and isinstance(value, list)
    }
    return sorted(class_level | instance_level)


def serialize_transform(transformer: Any) -> dict[str, Any]:
    """Serialize a transformer's output to a canonical, embedding-free dict.

    Args:
        transformer: A connector transformer exposing ``*_nodes`` / ``*_relationships``
            families, either as properties or as plain list attributes (e.g.
            ``CSVTransformer`` or ``UnityCatalogSchemaTransformer``).

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
        properties = {}
        for family in families:
            allowlist = transformer.get_properties(family)
            if allowlist:
                properties[family] = allowlist
        if properties:
            graph["_properties"] = properties
    return graph
