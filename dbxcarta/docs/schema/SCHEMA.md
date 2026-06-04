# dbxcarta Graph Schema

This document defines the Neo4j graph that `dbxcarta-spark` writes. It is the
authoritative contract between the pipeline and any client that reads the graph.
Pipelines write to this shape; clients query against it.

The enums that define labels, relationship types, and edge-source values live in
`dbxcarta.spark.contract` and are kept in sync with this document.

---

## Identifier generation

All node `id` values are produced by one of two deterministic functions:

**`generate_id(*parts)`** — joins lowercased, underscore-normalized parts with
dots. Used for Database, Schema, Table, and Column nodes.

```
catalog           → "my_catalog"
catalog, schema   → "my_catalog.finance"
catalog, schema, table            → "my_catalog.finance.orders"
catalog, schema, table, column    → "my_catalog.finance.orders.customer_id"
```

**`generate_value_id(column_id, value)`** — appends an MD5 hex digest of the
sampled value string to the owning column id.

```
"my_catalog.finance.orders.status.d41d8cd98f00b204e9800998ecf8427e"
```

Both functions are implemented in Python (`dbxcarta.spark.contract`) and as
equivalent Spark SQL expressions (`dbxcarta.spark.ingest.contract_expr`), so
ids are byte-identical whether produced on the driver or on executors.

---

## Nodes

### Database

One node per catalog ingested.

| Property             | Type    | Nullable | Notes                               |
|----------------------|---------|----------|-------------------------------------|
| `id`                 | string  | no       | `generate_id(catalog_name)`; unique |
| `name`               | string  | no       | catalog name                        |
| `platform`           | string  | yes      | cloud platform tag (e.g. `AWS`, `AZURE`, `GCP`); from `DBXCARTA_PLATFORM`, null when unset |
| `service`            | string  | no       | always `"DATABRICKS"`               |
| `description`        | string  | yes      | null today (no catalog comment in the extract) |
| `contract_version`   | string  | no       | schema version, currently `"1.1"`   |
| `embedding`          | float[] | yes      | 1024-dim cosine vector; present only when `DBXCARTA_INCLUDE_EMBEDDINGS_DATABASES=true` |

Neo4j constraint: `database_id` — `id IS UNIQUE`.

---

### Schema

One node per Unity Catalog schema in scope.

| Property             | Type    | Nullable | Notes                                |
|----------------------|---------|----------|--------------------------------------|
| `id`                 | string  | no       | `generate_id(catalog, schema)`; unique |
| `name`               | string  | no       | schema name                          |
| `description`        | string  | yes      | UC schema comment                    |
| `contract_version`   | string  | no       | `"1.1"`                              |
| `embedding`          | float[] | yes      | 1024-dim; present only when `DBXCARTA_INCLUDE_EMBEDDINGS_SCHEMAS=true` |

Neo4j constraint: `schema_id` — `id IS UNIQUE`.

---

### Table

One node per table or view in scope.

| Property             | Type      | Nullable | Notes                               |
|----------------------|-----------|----------|-------------------------------------|
| `id`                 | string    | no       | `generate_id(catalog, schema, table)`; unique |
| `name`               | string    | no       | table name                          |
| `layer`              | string    | yes      | optional catalog-derived layer such as `bronze`, `silver`, or `gold` |
| `table_type`         | string    | yes      | UC `table_type` (e.g. `MANAGED`, `EXTERNAL`, `VIEW`) |
| `description`        | string    | yes      | UC table comment                    |
| `created`            | timestamp | yes      | UC creation timestamp               |
| `last_altered`       | timestamp | yes      | UC last-altered timestamp           |
| `contract_version`   | string    | no       | `"1.1"`                             |
| `embedding`          | float[]   | yes      | 1024-dim; present only when `DBXCARTA_INCLUDE_EMBEDDINGS_TABLES=true` |

Neo4j constraint: `table_id` — `id IS UNIQUE`.
Vector index: `table_embedding` on `embedding` when embeddings are enabled.

---

### Column

One node per column in scope.

| Property             | Type    | Nullable | Notes                               |
|----------------------|---------|----------|-------------------------------------|
| `id`                 | string  | no       | `generate_id(catalog, schema, table, column)`; unique |
| `name`               | string  | no       | column name                         |
| `type`               | string  | yes      | UC data type string (e.g. `STRING`, `BIGINT`, `ARRAY<STRING>`) |
| `nullable`           | boolean | yes      | `true` / `false`; `null` when UC returns unexpected value |
| `ordinal_position`   | integer | yes      | 1-based column position             |
| `description`        | string  | yes      | UC column comment                   |
| `contract_version`   | string  | no       | `"1.1"`                             |
| `embedding`          | float[] | yes      | 1024-dim; present only when `DBXCARTA_INCLUDE_EMBEDDINGS_COLUMNS=true` |

Neo4j constraint: `column_id` — `id IS UNIQUE`.
Neo4j index: `column_type` on `type`.
Vector index: `column_embedding` on `embedding` when embeddings are enabled.

---

### Value

One node per sampled distinct value for STRING and BOOLEAN columns whose
cardinality falls below the configured threshold.

| Property             | Type    | Nullable | Notes                               |
|----------------------|---------|----------|-------------------------------------|
| `id`                 | string  | no       | `generate_value_id(column_id, value_str)`; unique |
| `value`              | string  | yes      | the sampled value as a string       |
| `count`              | long    | yes      | approximate row count for this value |
| `contract_version`   | string  | no       | `"1.1"`                             |
| `embedding`          | float[] | yes      | 1024-dim; present only when `DBXCARTA_INCLUDE_EMBEDDINGS_VALUES=true` |

Neo4j constraint: `value_id` — `id IS UNIQUE`.
Vector index: `value_embedding` on `embedding` when embeddings are enabled.

---

Embedding bookkeeping columns such as `embedding_text`,
`embedding_text_hash`, `embedding_model`, `embedded_at`, and
`embedding_error` are not graph properties. They live in the Delta staging
tables, the re-embedding ledger, and the run summary where applicable. The
Neo4j graph only carries the `embedding` vector itself.

---

## Relationships

All relationships are written with `MERGE` on source and target ids.

### HAS_SCHEMA

`(Database)-[:HAS_SCHEMA]->(Schema)`

No properties. One edge per Schema node.

---

### HAS_TABLE

`(Schema)-[:HAS_TABLE]->(Table)`

No properties. One edge per Table node.

---

### HAS_COLUMN

`(Table)-[:HAS_COLUMN]->(Column)`

No properties. One edge per Column node.

---

### HAS_VALUE

`(Column)-[:HAS_VALUE]->(Value)`

No properties. One edge per Value node.

---

### REFERENCES

`(Column)-[:REFERENCES]->(Column)`

Foreign-key relationships discovered from one or more sources.

| Property     | Type   | Nullable | Notes                                          |
|--------------|--------|----------|------------------------------------------------|
| `confidence` | float  | no       | 0.0–1.0; `1.0` for declared constraints        |
| `source`     | string | no       | provenance tag; see EdgeSource values below    |
| `criteria`   | string | yes      | human-readable inference reason, when present  |

**EdgeSource values** (written to `source`):

| Value               | Meaning                                              |
|---------------------|------------------------------------------------------|
| `declared`          | Unity Catalog declared foreign-key constraint        |
| `inferred_metadata` | Name/primary-key heuristic inference                 |

Readers should treat a missing `confidence`, `source`, or `criteria` property
as `(1.0, "declared", null)` via COALESCE for backwards compatibility.

---

## Embeddings

Embeddings are 1024-dimensional float vectors produced by `ai_query()` against
a Databricks Model Serving endpoint (default: `databricks-gte-large-en`,
configurable via `DBXCARTA_EMBEDDING_ENDPOINT`).

Each label has an independent feature flag:

| Label    | Flag                                      | Default |
|----------|-------------------------------------------|---------|
| Database | `DBXCARTA_INCLUDE_EMBEDDINGS_DATABASES`   | true    |
| Schema   | `DBXCARTA_INCLUDE_EMBEDDINGS_SCHEMAS`     | true    |
| Table    | `DBXCARTA_INCLUDE_EMBEDDINGS_TABLES`      | true    |
| Column   | `DBXCARTA_INCLUDE_EMBEDDINGS_COLUMNS`     | true    |
| Value    | `DBXCARTA_INCLUDE_EMBEDDINGS_VALUES`      | true    |

When a flag is disabled, the `embedding` property is absent from the
corresponding nodes. Vector indexes for that label are not created.

---

## Versioning

The current schema version is **`1.1`**, stored as `contract_version` on every
node. Adding a new property or relationship type increments the version.
Removing or renaming a property is a breaking change. Clients should treat
unknown properties as additive and not error on their presence.
