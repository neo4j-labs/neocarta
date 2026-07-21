"""Layer B: dump post-ingest Neo4j graph state to a deterministic dict.

Captures every node (labels + properties) and relationship (endpoint ``id``s + type
+ properties) after a connector has ingested into Neo4j, normalized so the snapshot
is byte-reproducible across runs, machines, and Neo4j Community/Enterprise editions:

- The ``__neocarta_graph__`` singleton is excluded — it carries wall-clock
  ``datetime()`` timestamps and the release version, and has no ``id``. Its behavior
  is characterized separately (shape-only invariants), never as frozen values.
- Neo4j internal/element ids are never read; endpoints are the deterministic ``id``
  property MERGEd by the loader.
- Order is normalized here (Neo4j does not guarantee return order): nodes by
  ``(labels, id)``, relationships by ``(type, src, dst)``, with a canonical-JSON
  tiebreaker; label lists and dict keys are sorted.
- ``embedding`` properties are dropped unless ``include_embeddings=True`` (used only
  by the enrichment-characterization test); float values are rounded to absorb
  float32 storage drift.
"""

from __future__ import annotations

import json
from typing import Any

from neo4j import Driver, RoutingControl

_EXCLUDED_PROPS = frozenset({"embedding"})
_METADATA_LABEL = "__neocarta_graph__"
_FLOAT_PRECISION = 5

_NODES_CYPHER = "MATCH (n) RETURN labels(n) AS labels, properties(n) AS properties"
_RELS_CYPHER = (
    "MATCH (a)-[r]->(b) "
    "RETURN type(r) AS type, a.id AS src, b.id AS dst, properties(r) AS properties"
)
_METADATA_CYPHER = (
    f"MATCH (n:`{_METADATA_LABEL}`) "
    "RETURN n.initial_version AS initial_version, n.latest_version AS latest_version, "
    "n.create_date AS create_date, n.last_updated AS last_updated"
)


def _coerce(value: Any) -> Any:
    """Coerce a Neo4j property value to a JSON-safe, precision-stable form."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return round(value, _FLOAT_PRECISION)
    if isinstance(value, list):
        return [_coerce(item) for item in value]
    return str(value)  # neo4j temporal/spatial types -> stable string


def _clean_props(props: dict[str, Any], *, include_embeddings: bool) -> dict[str, Any]:
    """Drop excluded keys and coerce remaining values to a JSON-safe form."""
    return {
        key: _coerce(value)
        for key, value in props.items()
        if include_embeddings or key not in _EXCLUDED_PROPS
    }


def _canonical(obj: Any) -> str:
    """A stable string form of ``obj`` for use as a sort tiebreaker."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def dump_graph(
    driver: Driver,
    database: str = "neo4j",
    *,
    include_embeddings: bool = False,
) -> dict[str, Any]:
    """Return a deterministic snapshot of all nodes + relationships in ``database``.

    Args:
        driver: A connected Neo4j driver.
        database: The database name to read from.
        include_embeddings: If ``True``, keep ``embedding`` properties (rounded);
            otherwise they are excluded. Only the enrichment-characterization test
            sets this — the core post-ingest graph is embedding-free.

    Returns:
        ``{"nodes": [...], "relationships": [...]}`` with the ``__neocarta_graph__``
        singleton excluded and ordering fully normalized.
    """
    node_records, _, _ = driver.execute_query(
        _NODES_CYPHER, routing_=RoutingControl.READ, database_=database
    )
    rel_records, _, _ = driver.execute_query(
        _RELS_CYPHER, routing_=RoutingControl.READ, database_=database
    )

    nodes: list[dict[str, Any]] = []
    for record in node_records:
        labels = sorted(record["labels"])
        if _METADATA_LABEL in labels:
            continue
        nodes.append(
            {
                "labels": labels,
                "properties": _clean_props(
                    dict(record["properties"]), include_embeddings=include_embeddings
                ),
            }
        )
    nodes.sort(
        key=lambda node: (node["labels"], str(node["properties"].get("id")), _canonical(node))
    )

    relationships = [
        {
            "type": record["type"],
            "src": record["src"],
            "dst": record["dst"],
            "properties": _clean_props(
                dict(record["properties"]), include_embeddings=include_embeddings
            ),
        }
        for record in rel_records
    ]
    relationships.sort(
        key=lambda rel: (rel["type"], str(rel["src"]), str(rel["dst"]), _canonical(rel))
    )

    return {"nodes": nodes, "relationships": relationships}


def fetch_metadata_node(driver: Driver, database: str = "neo4j") -> dict[str, Any] | None:
    """Return the ``__neocarta_graph__`` singleton's properties, or ``None`` if absent.

    Exposed so tests can characterize the excluded metadata node by *shape* invariants
    (version equality, ``create_date <= last_updated``) rather than frozen values.
    """
    records, _, _ = driver.execute_query(
        _METADATA_CYPHER, routing_=RoutingControl.READ, database_=database
    )
    return dict(records[0]) if records else None
