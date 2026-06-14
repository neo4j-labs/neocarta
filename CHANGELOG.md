# Changelog of neocarta library and MCP server


## Upcoming 

### Fixed

### Changed

### Added

- Add `scripts/setup_openai_endpoint.py`: an operational helper that registers a Databricks Mosaic AI External Models serving endpoint proxying OpenAI `text-embedding-3-small` (1536-dim), reading the OpenAI key from a Databricks secret (`neocarta-openai/OPENAI_API_KEY` by default), then probes it through the same `ai_query` path the connector uses to assert the returned vector dimension. This automates the "Registering the OpenAI endpoint (manual step)" section of `neocarta/connectors/databricks/README.md`, letting inline embeddings match an OpenAI-based neocarta graph. Run with `uv run scripts/setup_openai_endpoint.py --profile <profile>`; `--skip-verify` creates the endpoint without the probe.
- Add optional inline Spark embeddings to the `neocarta/connectors/databricks/` connector. The connector now supports two equal embedding modes. **External** (default, unchanged behavior): the Spark job writes Database/Schema/Table/Column nodes with no `embedding` property and creates no vector indexes; `neocarta.enrichment` adds vectors afterward. **Inline** (opt-in): when any `NEOCARTA_DATABRICKS_INCLUDE_EMBEDDINGS_{TABLES,COLUMNS,SCHEMAS,DATABASES}` flag is on, each batch embeds in-cluster via `ai_query('<endpoint>', embedding_text, failOnError => false)` against a Databricks model-serving endpoint (default `databricks-gte-large-en`, 1024-dim), and a per-label `{Label}_vector_index` cosine index is created at the configured dimension. New settings: `EMBEDDING_ENDPOINT`, `EMBEDDING_DIMENSION`, `EMBEDDING_BATCH_TABLES`, `EMBEDDING_FAILURE_MAX` (per-batch embedding-failure count gate; 0 disables it), and `EMBEDDING_STAGING_VOLUME` (required when inline is on; a `/Volumes/<cat>/<schema>/<vol>/<subdir>` subpath for the transient per-batch `ai_query` materialization). All inline flags default off, so external mode is the default. Value nodes are never embedded in either mode. See `neocarta/connectors/databricks/README.md` for the full mode comparison and the two-step external flow.
- Add the optional cross-run embedding ledger to the Databricks connector (inline mode only): a per-label Delta cache that reuses a node's stored vector when its id, model, and embedding-text SHA-256 hash are unchanged since the last run, so only changed rows call `ai_query`. Off by default; enabled with `NEOCARTA_DATABRICKS_LEDGER_ENABLED`, with the durable Delta root from `NEOCARTA_DATABRICKS_LEDGER_PATH` (blank derives a sibling of the staging volume).
- Add `NEOCARTA_DATABRICKS_SUMMARY_VOLUME` to the Databricks connector: an optional `/Volumes/<cat>/<schema>/<vol>/<subdir>` subpath where each run persists `summary_<run_id>.json` (the flattened `RunSummary`). Mode-independent (external and inline), durable, and best-effort: a write failure is logged, never raised, so it cannot mask the run outcome. Blank (default) disables persistence, leaving the summary returned in memory and the Neo4j counts logged. This gives a detached cluster job a durable run report. The `RunSummary.to_dict()` output shape carries the per-batch failure gate as the integer key `embedding_failure_max` (consistent with the `EMBEDDING_FAILURE_MAX` setting), not a rate threshold.
- Add the `neocarta databricks embed` CLI command: the external-mode hand-off as a first-class verb. Run it after the Spark ingest job to embed Database/Schema/Table/Column descriptions via `neocarta.enrichment.embeddings` and write the vectors back. Takes `--embedding-model`, `--embedding-dimensions`, `--dry-run`, and `--json`. The Spark schema ingest itself stays a cluster wheel job and is not a CLI verb.
- Add the `dbxcarta/` subtree: the Databricks semantic-layer capability that builds the neocarta graph from Unity Catalog with Spark. It ships as a `uv` workspace with the `dbxcarta-core` and `dbxcarta-spark` packages (published as the `neocarta[dbxcarta-core]` and `neocarta[dbxcarta-spark]` extras), plus the `dbxcarta-client`, `dbxcarta-submit`, and `dbxcarta-materialize` workspace packages. The `dbxcarta` dependency group installs the full toolchain, and `make dbxcarta-test`, `make dbxcarta-typecheck`, and the `e2e-*` targets delegate into the subtree. The dbxcarta extras require Python >=3.12, so the shared workspace lock and dev/CI now resolve at 3.12+; the published `neocarta` wheel still supports 3.10.
- Align the dbxcarta graph schema contract (`dbxcarta.spark.contract`, version `1.7`) with the neocarta core RDBMS model (`neocarta/data_model/rdbms/core.py`). Node text properties on `Schema`, `Table`, and `Column` are now `description` (was `comment`); the `Column` data type is `type` (was `data_type`) and its nullability boolean is `nullable` (was `is_nullable`). `Database` nodes gain `platform` (the cloud tag, supplied via the optional `DBXCARTA_PLATFORM` config and stored upper-cased, null when unset), `service` (the constant `"DATABRICKS"`), and `description` (null today, since the extract reads no catalog comment). `Column` nodes gain `is_primary_key` and `is_foreign_key`, derived at extract time from the catalog's DECLARED constraints (`information_schema.table_constraints` joined to `key_column_usage`) via a native Spark aggregate; this matches core's declared-only semantics, so inferred `REFERENCES` edges never set the flags. The `REFERENCES` edge endpoint join columns are now `source_column_id` / `target_column_id` (were `source_id` / `target_id`); the structural `HAS_*` edges are unchanged. Every run is a clean rebuild, so there is no legacy graph to migrate.

## v0.6.0

### Fixed

- Top-level `--debug` flag now actually prints the chained exception traceback to stderr when a `CLIError` is rendered. It was previously wired up but never read. The flag must precede the subcommand: `neocarta --debug bigquery schema ...`.

### Changed

- BigQuery error envelopes now include `vendor_exception`, `vendor_message`, and `vendor_http_status` in `details`, preserving the original `google.api_core.exceptions.*` class name, server-side message, and HTTP status code in the JSON output. The original exception is still reachable via `__cause__` (and rendered by `--debug`).
- MCP server uses LiteLLM embeddings now instead of OpenAI embeddings. OpenAI embeddings still available via LiteLLM.
- **Breaking:** MCP server settings: `embedding_dimensions` removed. `embedding_model` is the only embedding-related setting. Provider auth (`OPENAI_API_KEY`, `GEMINI_API_KEY`, `AZURE_`*, `AWS_`*, ...) is read directly by LiteLLM from standard env vars. Advanced overrides (LiteLLM Proxy, custom endpoints) move into the connector's `litellm_kwargs` argument.
- `create_openai_embedder` in `neocarta/_mcp/embeddings.py` renamed to `create_embedder`.
- Text2SQL agent chat LLM is now provider-agnostic via `langchain-litellm`. Model is configurable through the `AGENT_MODEL` env var (default `openai/gpt-4o-mini`); any LiteLLM model id is accepted (e.g. `gemini/gemini-2.0-flash`, `anthropic/claude-sonnet-4-5`).
- Shared Neo4j-driver and embedder helpers are factored from BigQuery CLI module into `neocarta/_cli/commands/_common.py` for all CLI commands to use.

### Added

- Add `neocarta.errors` module with a unified `NeocartaError` hierarchy: `ConfigError`, `AuthError`, `StateError`, `RateLimitError`, `OperationTimeoutError`, `ConnectorError`, `ExtractionError`, `TransformError`, `EnrichmentError`, and a `Neo4jError` subtree covering `Neo4jConnectionError`, `LoadError`, `ConstraintCreationError`, and `IndexCreationError`. Each class declares a `code` mapping to an existing CLI exit-code envelope; `RateLimitError` and `OperationTimeoutError` default to `retryable=True`. `StateError` is used for call-order/sequencing failures (e.g. calling `extract_entry_links()` before `extract_glossary_info()`), distinct from `ConfigError` for bad arguments.
- Add `LiteLLMEmbeddingsConnector`. OpenAI embeddings can be generated via this or the original `OpenAIEmbeddingsConnector`. Both now subclass a shared `BaseEmbeddingsConnector` in `neocarta.enrichment.embeddings.base` that owns the batch loop, dimension probing, vector-index creation, and Neo4j read/write; subclasses only override `__init__`, `_create_embedding_sync`, and `_create_embedding_async`.
- Add `litellm` dependency for multi-provider embedding support.
- Add `langchain-litellm` to the `agent` dep group for provider-agnostic agent chat LLM.
- Add `OsiConnector` for bidirectional [Open Semantic Interchange (OSI)](https://github.com/open-semantic-interchange/OSI) integration. `connector.ingest(spec_source)` reads an OSI YAML spec from a local path or HTTP(S) URL and loads it into Neo4j; `connector.export(semantic_model_name, output_path)` reads an OSI semantic model from Neo4j back into an OSI YAML file. Targets OSI **0.1.1** by default (see `OsiConnector.SUPPORTED_VERSIONS`); `connector.ingest(spec_source, version=...)` accepts a `version=` argument (default `"0.1.1"`) and emits an `UnsupportedOsiVersionWarning` (defined in the new `neocarta.warnings` module alongside `neocarta.errors`; subclass of the also-new `NeocartaWarning` base, which subclasses `UserWarning`) when the declared version is outside the supported set or when the parsed spec's `version` field is missing or doesn't match. New data model classes (`OsiSemanticModel`, `OsiTable`, `OsiColumn`, `Metric`, `Join`, `Expression`, `OsiAiContext`, `OsiCustomExtensions`) carry the OSI-specific entities; new relationship classes (`DomainHasTable`, `HasQuery`, `HasMetric`, `HasAspect`, `HasExpression`, `HasSourceTable`, `HasTargetTable`, `UsedInJoin`) wire them together. OSI synonyms in `ai_context` are upserted as `BusinessTerm` nodes (MERGE on `name`, so they dedupe against catalog-derived BTs from connectors like Dataplex). Query-source datasets are stored as `Query` nodes via `:HAS_QUERY`, with their projected fields attached through the existing `(Query)-[:USES_COLUMN]->(Column)` edge (same rel type used by the query_log connector). `Join` nodes carry ordered `from_columns` / `to_columns` lists so composite-key joins round-trip with positional pairing preserved. 
- Add `generate_osi_semantic_model_id`, `generate_metric_id`, `generate_join_id`, `generate_expression_id`, `generate_ai_context_id`, `generate_custom_extension_id`, `generate_query_column_id` to `connectors.utils.generate_id`.
- Extend `_build_node_ingest_query` with an optional `secondary_labels` argument so subtype labels (e.g. `:Table:OsiTable`, `:Aspect:OsiAiContext`) can be applied in a single MERGE. Existing call sites are unaffected (default is no secondary labels).
- Add `_run_write` helper to `Neo4jRDBMSLoader` for the common `execute_query`/`summary.counters` write pattern; reused by the new `OsiNeo4jLoader` subclass.
- Add `create_name_range_index` in `neocarta.ingest.indexes` and wire it into `Neo4jRDBMSLoader` so a RANGE index on `n.name` is created (when node constraints are written, before ingestion) for every name-bearing label: `Database`, `Schema`, `Table`, `Column`, `Glossary`, `Category`, `BusinessTerm`, and `CTE`. This backs the exact-equality `MATCH (n {name: ...})` lookups used by the MCP catalog queries, which previously fell back to a full label scan (vector and full-text indexes do not back equality matches). Creation is on by default and can be disabled per load method via `create_name_index=False`.
* Add `neocarta csv ingest` CLI command wrapping `CSVConnector` to load metadata from a directory of CSV files into Neo4j. Loads every entity CSV present (skipping missing files); the directory comes from `--csv-directory` or the `CSV_DIRECTORY` env var. Supports `--dry-run` and `--json`; embeddings are opt-in via `--embeddings` (default off). 

## v0.5.0

### Added

- Add `performance` optional extra (`pip install neocarta[performance]`) that pulls in `neo4j-rust-ext` for 60–90% faster Neo4j serialisation on bulk loads. Requires Python ≥ 3.11. The extension patches the `neo4j` driver automatically on import — no code changes needed.
- Add `neocarta` CLI (`pip install neocarta[cli]`) exposing `neocarta bigquery schema` and `neocarta bigquery logs` wrappers around the existing connectors. Global `--json` / TTY-detected output, `--no-color`, `--debug`, and `--dry-run` are supported. Connector settings resolve as flag → env var → default; secrets (`NEO4J_PASSWORD`, `OPENAI_API_KEY`, `GOOGLE_APPLICATION_CREDENTIALS`) are env-only. A `.env` file in the working directory is loaded automatically.
- Add `neocarta agent-context` command that emits the full CLI shape (commands, flags, exit codes, recognised env vars) as JSON for AI agents to discover at runtime. The `schema_version` field increments on breaking changes.

## v0.4.0

### Fixed

- Fixed `OpenAIEmbeddingsConnector.run()` and `arun()` closing caller-owned Neo4j drivers after embedding ingestion
- Fix demo data: `business_term_info.csv` had duplicate term identity columns (`term_name` as abbreviation and `name` as full readable name); removed `term_name` abbreviation column and renamed `name` → `term_name`. Updated `column_term_info.csv` and `table_term_info.csv` to reference terms by full readable name to match.
- Fixed query parser reading CTEs as real tables
- Fixed query parser reading `.*` projections as a real column named `*`
- Fixed query parser reading self referential joins as real FKs

### Changed

- MCP server now probes the target database at startup and registers retrieval tools per label by priority: business-term-bridged hybrid > hybrid (vector + full-text on same label) > vector or full-text alone. Schema-level vector retrieval and catalog tools are registered independently.
- **Breaking:** Renamed vector retrieval MCP tools for consistency with the new full-text / hybrid / business-term-hybrid tool naming. `get_metadata_schema_by_column_semantic_similarity` → `get_context_by_column_vector_search`; `get_metadata_schema_by_table_semantic_similarity` → `get_context_by_table_vector_search`; `get_metadata_schema_by_schema_and_table_semantic_similarity` → `get_context_by_schema_and_table_vector_search`. Cypher helper functions renamed correspondingly.
- `run_agent.py` no longer hardcodes a neocarta tool allowlist; it trusts whatever the neocarta MCP server exposes (since the server self-filters by index inventory) and only allowlists `execute_sql` from the BigQuery MCP server.
- Reorganised `neocarta/_mcp/` cypher into a `cypher/` subpackage (`catalog`, `vector_search`, `full_text_search`, `hybrid_search`) and split MCP tool registrations into a `tools/` subpackage with one module per retrieval strategy.

### Added

- Add data model diagram for table views and materialized views
- Add `claude.md` file
- Add `CTE` node to capture CTEs from queries 
- Add `(:Query)-[:DEFINES]->(:CTE)` relationship
- Add full-text search MCP tools: `get_context_by_table_full_text_search`, `get_context_by_column_full_text_search`.
- Add hybrid (vector + full-text on same node) MCP tools: `get_context_by_table_hybrid_search`, `get_context_by_column_hybrid_search`.
- Add business-term-bridged hybrid MCP tools: `get_context_by_table_business_term_hybrid_search`, `get_context_by_column_business_term_hybrid_search`. The full-text branch matches `:BusinessTerm` nodes and bridges to `:Table`/`:Column` nodes via `TAGGED_WITH`.
- Add `__neocarta_graph`__ singleton metadata node (`initial_version`, `latest_version`, `create_date`, `last_updated`). Connectors upsert it at the end of every `run()` so the graph carries a record of which neocarta version last wrote to it. The MCP server reads the node at startup and logs a warning when `latest_version` does not match the running server's neocarta version (or when the node is missing).

## v0.3.0

### Fixed

- Add column data types `["GEOGRAPHY", "JSON", "BIGNUMERIC"]` to skipped list for `Value` node creation. These types will throw an error otherwise.
- Implement `generate_*_id` functions for all ID generation tasks
- Fixed bug where value retrieval would yield empty arrays when all values in column are `NULL`
- Fixed bug where `description='false'` when querying table info due to inaccurate `INFORMATION_SCHEMA.TABLE_OPTIONS` filtering
- Update agent code to use new MCP configuration
- CSV connector `business_term_info.csv` now requires `glossary_name` and `category_name` in addition to `term_name`, ensuring business term IDs are globally unique within a CSV dataset (previously `term_id` alone was not uniquely scoped)
- Dataplex connector `Category` nodes previously used the full GCP resource path as both `id` and `name`; `id` is now a normalised dot-separated slug and `name` is the category slug

### Changed

- Replace `RESOLVES_TO` relationship with `TAGGED_WITH` across RDBMS and LPG data models
- **Breaking:** CSV connector glossary CSV files now use `*_name` columns as required inputs (matching the database hierarchy convention) — `glossary_id` → `glossary_name` in `glossary_info.csv`; `glossary_id`, `category_id` → `glossary_name`, `category_name` in `category_info.csv`; `category_id`, `term_id` → `glossary_name`, `category_name`, `term_name` in `business_term_info.csv`. IDs are now auto-generated as a dot-separated hierarchy from these name columns. Explicit `*_id` columns are still accepted as overrides.

### Added

- Add `TAGGED_WITH` relationship type to `RelationshipType` enum
- Add `TaggedWith` model to RDBMS expanded data model
- Add `extract_entry_links()` to `DataplexExtractor` — retrieves `TAGGED_WITH` links between BigQuery columns/tables and Dataplex glossary terms via the `lookupEntryLinks` REST API
- Add `transform_to_column_tagged_with_relationships()` and `transform_to_table_tagged_with_relationships()` to `DataplexTransformer`
- Add `load_column_tagged_with_relationships()` and `load_table_tagged_with_relationships()` to Neo4j loader
- `DataplexConnector` now creates `(:Column)-[:TAGGED_WITH]->(:BusinessTerm)` and `(:Table)-[:TAGGED_WITH]->(:BusinessTerm)` relationships when both `include_schema` and `include_glossary` are enabled
- Add acme dataset and update example dataset loader function to accomodate ecommerce and acme datasets
- Add optional `resource_path` property to `Glossary`, `Category`, and `BusinessTerm` nodes — intended to hold the full Dataplex resource path when loaded via the Dataplex connector
- Add `generate_glossary_id()`, `generate_category_id()`, and `generate_business_term_id()` to ID generation utilities
- CSV connector now supports loading glossary, category, and business term data; glossary entities follow the same `*_name` column convention as the database hierarchy, with IDs auto-generated as a dot-separated hierarchy (`glossary_name.category_name.term_name`)
- CSV connector now supports `(:Column)-[:TAGGED_WITH]->(:BusinessTerm)` and `(:Table)-[:TAGGED_WITH]->(:BusinessTerm)` relationships via `column_term_info.csv` and `table_term_info.csv`; both files support auto-generated or explicit IDs
- Add sample `column_term_info.csv` and `table_term_info.csv` to the ecommerce dataset
- Dataplex connector now uses `generate_glossary_id()`, `generate_category_id()`, and `generate_business_term_id()` for consistent dot-separated node IDs — IDs produced by the Dataplex and CSV connectors are now interoperable when glossary/category/term slugs match
- Dataplex connector sets `resource_path` on `Glossary`, `Category`, and `BusinessTerm` nodes with the original GCP resource path; glossary `resource_path` is inferred from the category resource path

## v0.2.1

### Fixed

- Remove duplicated docstrings in MCP server

### Added

- Update MCP documentation

## v0.2.0

### Changed

- Move MCP server to `neocarta` library
- Change MCP server name to `neocarta-mcp`
- Update MCP server imports in `eval/` module
- Deduplicate embedding code in MCP server. MCP server now uses `neocarta` embeddings class.
- Update Cypher queries in MCP server to follow same traversal patterns and return similar objects
- Update MCP tool documentation
- Lock `fastmcp` version <3.x

### Added

- Add integration tests for MCP server compatibility with neocarta graph
- Add `get_metadata_schema_by_table_semantic_similarity` tool to MCP server
- Add instructions to MCP server so agents are better able to utilize the tooling

## v0.1.0

Initial release
