# Add the Databricks connector and split dbxcarta operator tooling out

This PR brings the Databricks connector into neocarta and moves all the dbxcarta
operator tooling (CLI, wheel build/publish, job submit, Unity Catalog admin) out
into the separate dbxcarta repo. Neocarta now owns only the connector and ships
it as a versioned wheel, and dbxcarta pulls that wheel to run jobs. The two
projects are fully decoupled, with the wheel as the single handoff between them.
New examples show how to run ingest jobs and the options available.

## Changes
- Add the Databricks connector and Spark ingest pipeline under
  `neocarta/connectors/databricks/` (settings, contract, extract/transform/load,
  foreign-key discovery, embeddings, preflight, and a connector README).
- Remove all dbxcarta operator tooling from neocarta and move it to the external
  dbxcarta repo, following the split design in `dist/cli.md` and `dist/simple.md`.
- Keep neocarta and dbxcarta decoupled: neocarta publishes a versioned connector
  wheel, and dbxcarta pulls it to stage and run the job.
- Add `examples/databricks/` showing two ways to run a job, local submit via
  `dbxcarta-submit` and in-workspace notebooks, plus inline vs. external
  embeddings, a retrieval-strategy comparison script, and a graph Text2SQL example.
- Update tests for the new connector and remove tests/examples for tooling that
  moved to dbxcarta.

## Open questions

1. **Standardized embedding text.** Embedded text is now standardized across
   every connector and both Databricks modes. The shared path
   (`get_nodes_to_embed`) and the Databricks inline `EMBEDDING_TEXT_EXPR` both
   compose `name | type | description`, dropping any null or blank part. `type`
   exists only on Column nodes, so Database/Schema/Table embed as
   `name | description`. A node always embeds on at least its `name`, and
   selection is now `embedding IS NULL` alone. Before, the shared path
   (BigQuery, CSV, Dataplex, Databricks external) embedded only `description`,
   so names and types were never embedded and any node without a description was
   skipped; only Databricks inline embedded a composite, using the
   catalog-qualified name. **Keep the composed `name | type | description`, or
   revert to just `description`?**

2. **Databricks full-text (keyword) search.** The connector creates
   `schema_full_text_index`, `table_full_text_index`, and
   `column_full_text_index` via the shared
   `neocarta.ingest.indexes.create_full_text_index` helper, matching the MCP
   server and the other connectors (Database is not indexed). Each index covers
   `name | qualified_name | description`. Including the dotted `qualified_name`
   lets Lucene tokenize the path so the bare name still matches while
   catalog/schema words become searchable. This is lexical only;
   `qualified_name` is deliberately not in the embedded text, to keep embeddings
   identical across connectors. **Keep `qualified_name` in the Databricks
   full-text indexes (namespace disambiguation, but the connectors diverge), or
   drop it to match the others that index only `name` and `description`
   (consistent behavior, losing the disambiguation)?**

3. **Embedding endpoint setup script placement.**
   `scripts/setup_openai_external_model_endpoint.py` creates a Databricks
   External Model endpoint that proxies OpenAI, so the connector's inline
   embedding mode can `ai_query` OpenAI `text-embedding-3-small` and match the
   other connectors' embeddings. **Move this to the external `dbxcarta` repo, or
   keep it in `scripts/`?** It is Databricks-specific and depends only on
   `databricks-sdk` (argues for `dbxcarta`), but it exists to support the
   neocarta Databricks connector (argues for keeping it here).

## Open questions (short version)

1. **Embedding text:** keep the composed `name | type | description`, or revert
   to `description` only?
2. **Databricks full-text indexes:** keep `qualified_name` in them, or drop it
   to match the other connectors (`name` and `description` only)?
3. **`setup_openai_external_model_endpoint.py`:** keep it in `scripts/`, or move
   it to the `dbxcarta` repo?
