# OSI Connector

Connector for the [Open Semantic Interchange (OSI)](https://github.com/open-semantic-interchange/OSI) spec.

OSI is a YAML-based interchange format for semantic models. This connector is bidirectional:

- **Ingest** — read an OSI YAML spec (local file or URL) and load it into Neo4j as an `OsiSemanticModel` subgraph.
- **Export** — read an `OsiSemanticModel` subgraph from Neo4j (filtered by semantic model name) and emit an OSI YAML spec.

## Usage

```python
from neo4j import GraphDatabase

from neocarta.connectors.osi import OsiConnector

driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
connector = OsiConnector(neo4j_driver=driver, database_name="neo4j")

# Ingest an OSI spec from a local path or URL
connector.ingest("path/to/spec.yaml")
connector.ingest("https://example.com/spec.yaml")

# Export a semantic model from Neo4j back to OSI YAML
connector.export(semantic_model_name="my_model", output_path="out.yaml")
```

## Package layout

```
osi/
├── connector.py          # OsiConnector orchestration
├── ingest/
│   ├── extract.py        # OsiSpecExtractor: load YAML from path or URL
│   └── transform.py      # OsiIngestTransformer: OSI dict → graph models
└── export/
    ├── extract.py        # OsiGraphExtractor: Cypher reads filtered by semantic model name
    └── transform.py      # OsiExportTransformer: graph rows → OSI dict → YAML
```
