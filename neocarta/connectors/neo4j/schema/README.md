# Neo4jSchema Connector

## Overview

One paragraph: what source/format this reads, what entity types land in Neo4j,
and any attribution.

## Connector type

source (ingest only).

## Data model

```mermaid
graph LR
%% TODO: nodes + relationships this connector produces, with properties and KEY markers.
```

## Usage

```python
import os
from neo4j import GraphDatabase
from neocarta.connectors.neo4j.schema import Neo4jSchemaConnector

neo4j_driver = GraphDatabase.driver(
    uri=os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
)

connector = Neo4jSchemaConnector(neo4j_driver=neo4j_driver)
connector.ingest(source=...)  # TODO: real source argument
```

### Environment variables

- `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` — Neo4j connection.
- TODO: source-specific auth variables, if any.

### Filtering options

TODO: which `NodeLabel` / `RelationshipType` values apply, once filtering is added.

## Known issues / limitations

TODO.
