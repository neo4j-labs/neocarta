# Databricks Connector Schema Alignment

This note records how the Databricks connector schema lines up with the neocarta core graph schema. The canonical schema for every connector is defined by the Pydantic models in `neocarta/data_model/rdbms/core.py` (Database, Schema, Table, Column, References) and `neocarta/data_model/rdbms/expanded.py` (Value and the glossary, query, and OSI models). Those models set the node labels, relationship types, and property names that all connectors are expected to write.

## Where the schema is out of alignment

- The core models in `core.py` describe a minimal shape. Each node has an id, a name, a description, and an embedding, and Column adds type, nullable, and the two key flags. The Databricks connector writes a superset of that shape, so its output carries properties that no other connector produces.
- The extra Databricks properties are not added to the core models. They live in connector-specific subclasses in `expanded.py`, so `core.py` itself stays untouched and the divergence is contained in the subclasses.
- Every Databricks node also carries a `contract_version` marker. This is a connector bookkeeping field with no equivalent anywhere in the core schema.
- The Databricks REFERENCES edge carries provenance fields (`confidence` and `source`) that the core References model does not have. The core model only defines the two endpoint ids and an optional `criteria`.
- The connector defines its own `EdgeSource` provenance enum for FK edges. neocarta has no repo-wide edge-provenance concept, so this is Databricks-only.

## What was changed in the dbxcarta branch

The dbxcarta branch did the work of pointing the Databricks ingest at the core neo4j schema instead of a private one. The key changes, tracked by its contract version history, were:

- Renamed the human-readable text property on Schema, Table, and Column from `comment` to `description` to match core. The Unity Catalog source column is still `comment`; only the graph property name changed.
- Renamed the Column data type property from `data_type` to `type`, and the Column nullability boolean from `is_nullable` to `nullable`, both to match core.
- Added Database properties to match core: `service` (the constant "DATABRICKS"), `platform` (the cloud tag, stored upper-cased), and `description` (null today because Unity Catalog exposes no catalog comment in the extract).
- Added the Column `is_primary_key` and `is_foreign_key` booleans, derived from declared catalog constraints, matching the declared-only semantics in core.
- Removed the leftovers of semantic-similarity FK inference, including the `is_key_like` property, the `KeyColumn` label, and the `semantic` edge-source value, so the emitted shape no longer carries fields that core does not know about.
- Despite all of the above, the dbxcarta branch still kept its own private copies of the contract. It defined its own `NodeLabel`, `RelType`, and `EdgeSource` enums, its own graph-label and graph-version constants, and a hand-maintained `NODE_PROPERTIES` dictionary, all inside `dbxcarta-spark/contract.py` rather than reusing neocarta's shared enums and models.

## What needs to change in this branch

This branch ports the connector into `neocarta/connectors/databricks/` and finishes the alignment that the dbxcarta branch started. The remaining work is to stop duplicating the contract and reuse neocarta's own definitions:

- Import node labels and relationship types from `neocarta.enums` (NodeLabel and RelationshipType) instead of the connector's private StrEnum copies. This is already done in the ported `contract.py`.
- Derive the connector's per-label property lists from Pydantic models rather than a hand-maintained dictionary. This branch adds `DatabricksDatabase`, `DatabricksSchema`, `DatabricksTable`, `DatabricksColumn`, `DatabricksValue`, and `DatabricksReferences` to `expanded.py`. Each subclasses the matching core model and adds only the connector's extra fields, so the core shape is inherited rather than restated.
- Keep the `EdgeSource` provenance enum connector-local, since core has no equivalent. It stays in `contract.py`.
- Confirm the ported connector writes through the shared ingest helpers for constraints and indexes (`neocarta.ingest`), so the Databricks output uses the same id constraints and vector index names that the rest of neocarta and the MCP server expect.

## Extra fields the Databricks connector adds beyond core

These are the properties the Databricks subclasses add on top of the core models. They are all additive, and readers of a core-only graph treat them as absent.

- **Database**: `contract_version`.
- **Schema**: `contract_version`.
- **Table**: `catalog`, `schema`, `layer` (medallion bronze/silver/gold), `table_type` (managed, external, or view), `created`, `last_altered`, `contract_version`.
- **Column**: `catalog`, `schema`, `table`, `ordinal_position`, `contract_version`.
- **Value**: `count`, `catalog`, `schema`, `last_run` (run-start stamp used for scoped stale-value cleanup), `contract_version`. The core Value model has only `id` and `value`. Value is never embedded: the connector builds no Value embedding, defines no Value vector index, and is reached only by HAS_VALUE traversal.
- **References edge**: `confidence` and `source` (FK provenance: declared or inferred from metadata). The core References model has only the endpoint ids and `criteria`.

The `catalog`, `schema`, and `table` properties exist to make structural identity a first-class scalar on Table and Column, so consumers do not have to re-derive position from the hashed id or the HAS_* edges.
