"""The LPG-owned graph vocabulary that the Neo4j connector reserves.

Neocarta writes its semantic layer using a fixed set of node labels and
relationship types (the ones :class:`~neocarta.ingest.lpg.load.Neo4jLPGLoader`
emits). When a Neo4j *source* connector reads a graph that happens to live in
the same database as the target semantic layer — or a previous ingest's output —
``apoc.meta.schema()`` reports Neocarta's own metadata back as if it were source
schema. Re-ingesting that would append the connector's self-description to the
graph, so ingest would not be idempotent.

To keep same-database ingest idempotent, the extractor excludes these reserved
labels and relationship types (see
``neocarta.connectors.neo4j.schema.extract``). This module is the single source
of truth for that vocabulary so the extractor's exclusion set and the loader's
output cannot drift: any label or type the loader learns to write must be added
here too.

The trade-off is a reserved namespace — a genuine source label/type that
collides with one of these names is indistinguishable from Neocarta's own
metadata and is dropped. This is documented as part of the connector contract.
"""

from ...enums import NodeLabel, RelationshipType

RESERVED_NODE_LABELS: frozenset[NodeLabel] = frozenset(
    {
        NodeLabel.DATABASE,
        NodeLabel.SCHEMA,
        NodeLabel.NODE,
        NodeLabel.RELATIONSHIP,
        NodeLabel.PROPERTY,
        NodeLabel.NEOCARTA_GRAPH,
    }
)
"""Node labels the LPG loader writes; excluded from same-database extraction."""

RESERVED_RELATIONSHIP_TYPES: frozenset[RelationshipType] = frozenset(
    {
        RelationshipType.HAS_SCHEMA,
        RelationshipType.HAS_NODE,
        RelationshipType.HAS_RELATIONSHIP,
        RelationshipType.HAS_SOURCE_NODE,
        RelationshipType.HAS_TARGET_NODE,
        RelationshipType.HAS_PROPERTY,
    }
)
"""Relationship types the LPG loader writes; excluded from same-database extraction."""
