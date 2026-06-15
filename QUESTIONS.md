# Decisions Needed

A running log of outstanding questions and decisions for Neocarta.

## Standardized embedding text

- Embedded text is now standardized across every connector and both Databricks modes.
- The shared path (`get_nodes_to_embed`) and the Databricks inline `EMBEDDING_TEXT_EXPR` both compose `name | type | description`, dropping any null/blank part.
- `type` exists only on Column nodes, so Database/Schema/Table embed as `name | description`.
- A node always embeds on at least its `name`; selection is now `embedding IS NULL` alone.
- Before: the shared path (BigQuery, CSV, Dataplex, Databricks external) embedded only `description`, so names/types were never embedded and any node without a description was skipped. Only Databricks inline embedded a composite, using the catalog-qualified name.

**Open question:** Keep the composed `name | type | description`, or revert to just `description`?


## Databricks full-text (keyword) search

- The Databricks connector creates `schema_full_text_index`, `table_full_text_index`, and `column_full_text_index` via the shared `neocarta.ingest.indexes.create_full_text_index` helper, matching the MCP server and the other connectors. Database is not indexed.
- Each index covers `name | qualified_name | description`.
- Including the dotted `qualified_name` lets Lucene tokenize the path so the bare name still matches while catalog/schema words become searchable.
- This is lexical only: `qualified_name` is deliberately not in the embedded text, to keep embeddings identical across connectors.

**Open question:** Keep `qualified_name` in the Databricks full-text indexes, or drop it to match the others (which index only `name` and `description`)?

- Keep it: namespace disambiguation on a Databricks graph, but the connectors diverge.
- Drop it: consistent behavior across connectors, losing the disambiguation.

## Embedding endpoint setup script placement

- `scripts/setup_openai_external_model_endpoint.py` creates a Databricks External Model endpoint that proxies OpenAI, so the connector's inline embedding mode can `ai_query` OpenAI `text-embedding-3-small` and match the other connectors' embeddings.

**Open question:** Move this to the external `dbxcarta` repo, or keep it in `scripts/`? It is Databricks-specific and depends only on `databricks-sdk` (argues for `dbxcarta`), but it exists to support the neocarta Databricks connector (argues for keeping it here).
