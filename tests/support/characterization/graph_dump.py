"""Layer B: dump post-ingest Neo4j graph state to a deterministic dict.

Captures every node (labels + properties) and relationship (endpoint ``id``s + type +
properties) after a connector ingests into Neo4j, normalized so the snapshot is
byte-reproducible across runs and machines:

- The ``__neocarta_graph__`` singleton is excluded — it carries wall-clock
  ``datetime()`` timestamps and the release version.
- Endpoints use the deterministic application ``id`` the loader MERGEs on, never
  Neo4j's internal/element ids.
- Order is normalized here (Neo4j does not guarantee return order): every node and
  relationship is sorted by its own canonical JSON, and label lists are sorted.

The captured node/relationship data is edition-agnostic (Neo4j Community and Enterprise
differ only in constraint *declarations*, which are not part of the graph).
"""

from __future__ import annotations

import json
from typing import Any

from neo4j import Driver, RoutingControl

_METADATA_LABEL = "__neocarta_graph__"
_NODES_CYPHER = "MATCH (n) RETURN labels(n) AS labels, properties(n) AS properties"
_RELS_CYPHER = (
    "MATCH (a)-[r]->(b) "
    "RETURN type(r) AS type, a.id AS src, b.id AS dst, properties(r) AS properties"
)


def _by_content(item: dict[str, Any]) -> str:
    """Total-order sort key: the item's own canonical JSON (deterministic)."""
    return json.dumps(item, sort_keys=True, ensure_ascii=False)


def dump_graph(driver: Driver, database: str = "neo4j") -> dict[str, Any]:
    """Return a deterministic snapshot of all nodes + relationships in ``database``.

    Args:
        driver: A connected Neo4j driver.
        database: The database name to read from.

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

    nodes = [
        {"labels": sorted(record["labels"]), "properties": dict(record["properties"])}
        for record in node_records
        if _METADATA_LABEL not in record["labels"]
    ]
    relationships = [
        {
            "type": record["type"],
            "src": record["src"],
            "dst": record["dst"],
            "properties": dict(record["properties"]),
        }
        for record in rel_records
    ]
    nodes.sort(key=_by_content)
    relationships.sort(key=_by_content)
    return {"nodes": nodes, "relationships": relationships}
