# Neo4j Connector

## Overview

This connector reads a **source Neo4j instance's schema** — its node labels,
relationship types, and properties — and records it in this library's graph data
model. It reads the schema via APOC's
[`apoc.meta.schema()`](https://neo4j.com/docs/apoc/current/overview/apoc.meta/apoc.meta.schema/)
and maps it onto the **LPG (Labeled Property Graph)** data model
(`neocarta.data_model.schema.lpg`), so an agent can see how a graph database is
organized the way the other connectors expose relational sources.

The source Neo4j and the target neocarta graph are both Neo4j, so the connector
takes **two drivers** (they may point at the same instance).

## Connector type

Source connector (ingest only). It provides one data-type sub-connector:

- `Neo4jSchemaConnector` — a source Neo4j's schema → `Database` / `Schema` /
  `Node` / `Relationship` / `Property`.

## Data model

Maps a source Neo4j onto the LPG data model: the source DBMS → `Database` (named
by the caller), the introspected database → `Schema`, each node label → `Node`,
each relationship type → `Relationship`, and each property key → `Property`
(owner-scoped, carrying its `type` and `unique` / `indexed` / `existence` flags).

```mermaid
---
config:
    layout: elk
---
graph LR
Database("Database<br/>id: STRING | KEY<br/>name: STRING<br/>service: STRING<br/>embedding: VECTOR")
Schema("Schema<br/>id: STRING | KEY<br/>name: STRING<br/>description: STRING<br/>embedding: VECTOR")
Node("Node<br/>id: STRING | KEY<br/>label: STRING<br/>additionalLabels: LIST<br/>description: STRING<br/>embedding: VECTOR")
Relationship("Relationship<br/>id: STRING | KEY<br/>type: STRING<br/>description: STRING<br/>embedding: VECTOR")
Property("Property<br/>id: STRING | KEY<br/>name: STRING<br/>type: STRING<br/>unique: BOOLEAN<br/>nullable: BOOLEAN<br/>indexed: BOOLEAN<br/>existence: BOOLEAN<br/>embedding: VECTOR")

Database -->|HAS_SCHEMA| Schema
Schema -->|HAS_NODE| Node
Schema -->|HAS_RELATIONSHIP| Relationship
Relationship -->|HAS_SOURCE_NODE| Node
Relationship -->|HAS_TARGET_NODE| Node
Node -->|HAS_PROPERTY| Property
Relationship -->|HAS_PROPERTY| Property
```

## Usage

```python
import os

from neo4j import GraphDatabase

from neocarta.connectors.neo4j import Neo4jSchemaConnector

# Read the schema from the source Neo4j; write the neocarta graph to the target.
source_driver = GraphDatabase.driver(
    os.getenv("SOURCE_NEO4J_URI"),
    auth=(os.getenv("SOURCE_NEO4J_USERNAME"), os.getenv("SOURCE_NEO4J_PASSWORD")),
)
target_driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
)

Neo4jSchemaConnector(
    source_neo4j_driver=source_driver,
    neo4j_driver=target_driver,
    source_name="prod-neo4j",       # names the source DBMS (the Database node id)
    database_name="neo4j",          # target neocarta database
).ingest(source_database="neo4j")   # which source database to introspect
```

**Environment variables:** `SOURCE_NEO4J_URI` / `SOURCE_NEO4J_USERNAME` /
`SOURCE_NEO4J_PASSWORD` for the source; `NEO4J_URI` / `NEO4J_USERNAME` /
`NEO4J_PASSWORD` / `NEO4J_DATABASE` for the target.

**Filtering:** `ingest()` / `extract()` accept `include_nodes` and
`include_relationships` (the shared `NodeLabel` / `RelationshipType` enums) to load
a subset — e.g. `include_nodes=[NodeLabel.NODE, NodeLabel.RELATIONSHIP]` to skip
properties.

A runnable example lives in [`examples/neo4j_schema.py`](../../../examples/neo4j_schema.py).

## Source-specific setup

The **source** Neo4j must have the **APOC (Core) plugin** installed, and the role
used to connect must be allowed to call `apoc.meta.schema()`. The connector runs a
pre-flight check and raises a clear `ConfigError` (with an install hint) if APOC is
absent. APOC Core ships with the official Neo4j Docker image and is enabled with
`NEO4J_PLUGINS='["apoc"]'`.

## Known issues / limitations

- **APOC is required on the source** (see above).
- **Per-label schema view.** `apoc.meta.schema()` reports schema per single label,
  so a multi-label node is represented as one `Node` per label and
  `additionalLabels` is not populated. Multi-label combinations are out of scope
  for this first implementation.
- **Existence constraints are Enterprise-only**, so `Property.existence` is always
  `False` against Community Edition (and `nullable` defaults to `True`).
- **Schema only** — the connector reads the schema, not instance data; it produces
  no `Value` nodes.
- **Re-ingest is additive.** Loads MERGE by id and never delete, so re-running
  updates the description in place.
- **Reserved LPG namespace (repeated ingest is idempotent).** The Neo4j connector
  reserves neocarta's own graph vocabulary and **never ingests it as source schema** —
  always, regardless of how the drivers or databases are configured. Reserved are the
  six node labels `Database` / `Schema` / `Node` / `Relationship` / `Property` /
  `__neocarta_graph__`, the six relationship types `HAS_SCHEMA` / `HAS_NODE` /
  `HAS_RELATIONSHIP` / `HAS_SOURCE_NODE` / `HAS_TARGET_NODE` / `HAS_PROPERTY`, and any
  relationship endpoint touching either set. This guarantees that pointing the
  connector at a source that shares a database with the target — or re-ingesting a
  previous run's output — is idempotent: re-running never accumulates a description of
  neocarta's own metadata. On single-database editions (Neo4j Community) the source and
  target are necessarily the same database, so this protection is what keeps ingest
  stable there. The single source of truth for the reserved set is
  `neocarta.ingest.lpg.RESERVED_NODE_LABELS` / `RESERVED_RELATIONSHIP_TYPES`. The
  trade-off is a genuine reservation: a source that legitimately uses one of these
  names is indistinguishable from neocarta's metadata and is **dropped, with a
  `Neo4jSchemaWarning`** — using a separate database or instance does **not** exempt it.
- **Case-sensitive identifiers.** Neo4j labels, relationship types, and property
  keys are case-sensitive, so `Person` and `person` map to distinct `Node`s and
  their ids preserve case verbatim. The `source_name` and source database name that
  scope those ids are normalized (lower-cased).
- **The caller owns both drivers.** `close()` is a no-op and never closes either
  driver; the caller is responsible for their lifecycle.
