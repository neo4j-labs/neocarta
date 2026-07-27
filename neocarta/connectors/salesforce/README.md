# Salesforce Connector

Loads a Salesforce org schema into Neo4j using the neocarta domain model.

## Data model

```
(Database)-[:HAS_SCHEMA]->(Schema)
(Schema)-[:HAS_TABLE]->(Table)
(Table)-[:HAS_COLUMN]->(Column)
(Column)-[:REFERENCES]->(Column)   ← foreign keys / lookup fields
```

Salesforce-specific properties are set on top of the core model:

| Node | Extra properties |
|---|---|
| `Table` | `label`, `labelPlural`, `keyPrefix`, `namespace`, `isCustom`, `isQueryable`, `isCreateable`, `isUpdateable`, `isDeletable` |
| `Column` | `label`, `length`, `precision`, `scale`, `isUnique`, `picklistValues` |

## Namespace / schema mapping

Salesforce object names are mapped to neocarta schemas by namespace:

| Object name pattern | Schema |
|---|---|
| `Account`, `Contact`, … (standard) | `core` |
| `Acme__Widget__c` (managed package) | `acme` |
| `My_Widget__c` (unmanaged custom) | `custom` |
| System objects not in the described set (`User`, `RecordType`, …) | `system` |

Namespace is extracted from the `NAMESPACE__ObjectName__c` prefix pattern. A valid namespace prefix contains only alphanumeric characters (no underscores), so objects like `CPP_CC_Entry__c` correctly fall through to `custom`.

## `description` field

neocarta's `description` is used for vector embeddings (semantic search / GraphRAG). The connector populates it as:

- **Both `label` and `description` present**: `"Account Name — The name of the account"` (concatenated for richer embeddings)
- **Only `label`** (the common case for standard objects): `"Account Name"`
- **Neither**: `None`

The `label` is also stored as a separate `label` property on each node via supplementary Cypher.

## References to system objects

Salesforce lookup fields often reference system objects (`User`, `RecordType`, `Group`, `Profile`) that are not returned by `sobject describe`. Rather than silently dropping these edges, the connector uses `MERGE` on the target Column node, creating a minimal stub with only an `id` property. These stubs are assigned to the `system` schema and can be enriched later.

## Architecture

```
SalesforceExtractor          SalesforceObjectDict[]  →  DataFrames
     ↓
CSVTransformer               DataFrames  →  neocarta Pydantic model objects
     ↓
Neo4jRDBMSLoader             Pydantic objects  →  Neo4j (MERGE on id)
     ↓
Supplementary Cypher         SET SFDC-specific properties on Table / Column
     ↓
MERGE_REFERENCES Cypher      Create REFERENCES edges (+ stub Column nodes)
```

The extractor produces DataFrames with the exact column layout expected by `CSVTransformer`, allowing the Salesforce connector to reuse the CSV connector's transform layer without modification.

## Usage

```python
from neocarta.connectors.salesforce import SalesforceConnector

# `objects` is a list of dicts from sf sobject describe / Salesforce REST API
connector = SalesforceConnector(
    objects=objects,
    org_name="my-org",
    neo4j_driver=driver,
    database_name="neo4j",
    output_dir=Path("/tmp/sfdc-csvs"),  # optional: write DataFrames to CSV
    batch_size=500,
)
connector.run()
```

Or step-by-step:

```python
connector.extract_metadata()    # populate extractor cache
connector.transform_metadata()  # convert to Pydantic model objects
connector.load_metadata(overwrite_existing=False)  # write to Neo4j
```

## Input format

Each object dict follows the shape of the Salesforce REST API
`GET /services/data/vXX/sobjects/{SObject}/describe` response, or the
equivalent `sf sobject describe --sobject <Name>` CLI output:

```json
{
  "name": "Account",
  "label": "Account",
  "labelPlural": "Accounts",
  "keyPrefix": "001",
  "custom": false,
  "queryable": true,
  "createable": true,
  "updateable": true,
  "deletable": false,
  "fields": [
    {
      "name": "Id",
      "label": "Account ID",
      "type": "id",
      "length": 18,
      "nillable": false,
      "unique": false,
      "referenceTo": [],
      "picklistValues": []
    }
  ]
}
```

## Running integration tests

Integration tests use a real Neo4j instance when `NEO4J_URI` is set, otherwise fall back to testcontainers (requires Docker).

```bash
NEO4J_URI=bolt://localhost NEO4J_USERNAME=neo4j NEO4J_PASSWORD=password \
  uv run pytest tests/integration/connectors/salesforce/ -v
```

Tests always run against the `neo4j` default database — the production database is never touched.
