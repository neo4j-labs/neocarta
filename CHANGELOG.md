# Changelog of neocarta library and MCP server

## Upcoming

### Fixed

### Changed

### Added

- `JdbcSchemaConnector` (`neocarta.connectors.jdbc`): a source connector that extracts schema metadata (`Database`, `Schema`, `Table`, `Column`, and `REFERENCES` foreign-key edges) from any JDBC-compatible database (PostgreSQL, MySQL, Oracle, SQL Server, Redshift, …). The Java↔Python bridge shells out to the SchemaCrawler CLI's `template` command with a bundled FreeMarker template (`schema/catalog.json.ftl`) that renders a compact JSON catalog with full table/column/primary-key/foreign-key detail, then flattens it into the shared `Neo4jRDBMSLoader` pipeline. (SchemaCrawler's `serialize` JSON omits tables and foreign keys, so the template is required to populate `REFERENCES`.) Host prerequisites — Java 11+, the SchemaCrawler distribution (its `_schemacrawler/lib/*` classpath), a FreeMarker JAR on that classpath, and a JDBC driver JAR — are user-supplied (Java availability is checked at construction; all documented in `neocarta/connectors/jdbc/README.md`). The DB password is passed to SchemaCrawler via the environment, never on the command line. Extraction is scoped with `ingest(schemas=[...])`. Ships unit tests (mocked subprocess + a real captured golden fixture) and a skip-guarded Dockerized-PostgreSQL integration test (`tests/integration/connectors/jdbc/`), plus `examples/jdbc.py` and `JDBC_*` entries in `.env.example`.

## v0.7.0 

### Fixed

- MCP server integration tests (`tests/integration/_mcp/test_server_IT.py`) no longer hit the real embedding provider. The batched-embedding change routes graph enrichment through the new `_create_embeddings_sync` / `_create_embeddings_async` batch methods, but the test `MockEmbeddingsConnector` only overrode the single-item `_create_embedding_*` methods — so the module-scoped `loaded_graph` fixture fell through to `litellm`, erroring all eight tests (a 401 in CI with `OPENAI_API_KEY=dummy`, a dimension mismatch locally with a real key). The mock now also overrides the batch methods.
- Connector lifecycle state-tracking. `extract()` on every connector now resets the downstream `_extracted` / `_transformed` flags so a stale prior `transform()` can't be inadvertently `load()`ed after a second `extract()`. `load()` now checks `_transformed` (not `_extracted`), enforcing the lifecycle rule from `.claude/skills/add-source-connector/connector-contract.md` §9 instead of accepting any extract-followed-by-load sequence.
- Embedding generation now sends one batched request per `batch_size` chunk instead of one request per node, which is much faster on large graphs. The sync and async embedders (`LiteLLMEmbeddingsConnector`, `OpenAIEmbeddingsConnector`) embed each chunk in a single `embedding(input=[...])` call. Closes #173.

### Changed

- **Breaking:** Connector public API standardized. All connectors now expose `extract()` / `transform()` / `load()` as public stages (renamed from `extract_metadata` / `transform_metadata` / `load_metadata`) plus an `ingest()` orchestrator. Format connectors additionally expose `export()` as the sole public method for the export direction; its internal stages (graph read, source-format build, file write) are private. The legacy `run()` entrypoint is preserved on every connector as a thin wrapper emitting a `DeprecationWarning`; it will be removed after approximately three releases.
- **Breaking:** `DataplexConnector` split into two purpose-scoped sub-connectors: `DataplexSchemaConnector` (BigQuery catalog metadata) and `DataplexGlossaryConnector` (business glossary + catalog↔glossary entry links that back TAGGED_WITH edges). The combined class with `include_schema` / `include_glossary` flags is removed. Schema must be ingested before glossary so TAGGED_WITH edges find their target Column / Table nodes.
- **Breaking:** Connector `__init__.py` exports trimmed to the connector class plus connector-specific warnings/errors only. Internal `Extractor` / `Transformer` / `Loader` classes are no longer re-exported from connector package roots; import them via their full module paths (e.g. `from neocarta.connectors.bigquery.schema.extract import BigQuerySchemaExtractor`).
- Passing `dataset_id` to `BigQuerySchemaConnector.__init__` is deprecated and emits a `DeprecationWarning`; pass it to `.ingest(dataset_id=...)` / `.extract(dataset_id=...)` instead. The constructor still accepts it as a fallback for callers that have not yet migrated.
- BigQuery `bigquery/schema/` and `bigquery/query_log/` subpackages now match the source-connector layout from the new connector standard (sub-folders by data type).
- The connector standard (formerly `docs/connector-refactor-guidance.md`, written for the now-complete refactor PR) has been migrated into the `add-source-connector` skill: the prose contract lives in `.claude/skills/add-source-connector/connector-contract.md` and the skill ships `scripts/driver.py` to scaffold and verify connectors against it. The standalone doc is removed; `connector-contract.md` is now the canonical reference (cross-referenced from `neocarta/connectors/_base.py` and the connector conformance tests).
- The shared CLI embedder helper `_build_embedder` now generates embeddings via `LiteLLMEmbeddingsConnector` instead of `OpenAIEmbeddingsConnector`, so the `bigquery`, `csv`, and `dataplex` CLI commands all embed through LiteLLM. Provider auth is read from environment variables based on the `embedding_model` (e.g. `OPENAI_API_KEY`, `GEMINI_API_KEY`) and the vector dimension is auto-detected, so `OPENAI_API_KEY` is no longer hard-required.
- CLI embedding runs now surface provider/credential failures (missing or invalid key, unknown model) as the standard `upstream_error` JSON envelope (exit 8) instead of an uncaught traceback, via a shared `_run_embeddings` helper wired into the `bigquery` (`schema`, `logs`), `csv`, and `dataplex` (`schema`, `glossary`) commands. The `--embedding-dimensions` flag is functional again: when set it is forwarded to LiteLLM via `litellm_kwargs` for models that support dimension truncation, otherwise the model's native size is used; the flag is also added to the `dataplex` commands for parity (supersedes the earlier note about removing it). The unused `openai_api_key` field was removed from the internal CLI settings (LiteLLM reads provider keys from the environment directly).
- Synced the data model mermaid diagrams (`assets/mermaid/data_model/`) and the data model / connector READMEs with the current `neocarta/data_model/` classes: property names now use snake_case (`is_primary_key`, `is_foreign_key`, `additional_labels`) matching the persisted Neo4j properties; glossary nodes (`Glossary`, `Category`, `BusinessTerm`) show the `resource_path` property; the query-log diagram and README include the `CTE` node and `(:Query)-[:DEFINES]->(:CTE)` relationship. `rdbms/README.md` line-number anchors were corrected, an OSI semantic-model section was added, and the obsolete "Metrics + KPIs (Not Implemented)" section was removed (now implemented via OSI). Data-model image generation in the `Makefile` now renders every diagram at `--scale 2` with a transparent background.
* Agent unit tests (`tests/unit/agent/`) now run in a dedicated CI job and `make test-agent` target with the `agent` dependency group installed; `make test-unit` skips them — mirroring how MCP and CLI tests are isolated. This prevents the default unit run from failing to import `langgraph` when the optional `agent` group is not installed.

### Added

- `OsiConnector.extract()` / `.transform()` / `.load()` as public ingest-stage methods, matching the source-connector contract. `OsiSpecExtractor` now takes `spec_source` on `.extract(spec_source)` instead of `__init__`, so the connector can pre-instantiate the extractor in its constructor.
- `DataplexSchemaConnector` and `DataplexGlossaryConnector` with `extract` / `transform` / `load` / `ingest` stages. The glossary connector's `extract(include_entry_links=...)` lets callers skip the REST-API round-trips when the catalog is not present in the same Neo4j instance.
- `StateError` is now raised by `transform()` / `load()` when called out of order on any connector.
- `neocarta.connectors._base` defining `SourceConnectorProtocol` and `FormatConnectorProtocol`. Both are `runtime_checkable`, codifying the prose spec into executable contracts that conformance tests assert against.
- Per-connector conformance test suite (`tests/unit/connectors/*/test_conformance.py`) covering: protocol conformance, public stage methods, `run()` DeprecationWarning, `README.md` presence, `__init__.py` export minimality, `StateError` on out-of-order calls, and BigQuery-schema-specific `dataset_id`-in-`__init__` deprecation warning.
- Spec §5 narrow exception for bespoke flags that can't be expressed via `include_nodes` / `include_relationships` (e.g. extra REST round trips, optional connector-specific phases). Used by `DataplexGlossaryConnector.extract(include_entry_links=...)`.
* Add `neocarta dataplex schema` and `neocarta dataplex glossary` CLI commands, wrapping `DataplexSchemaConnector` and `DataplexGlossaryConnector` (the noun is the source, the verb is the subgraph component, matching `bigquery schema` / `bigquery logs`). `dataplex schema` loads BigQuery catalog metadata (`Database`, `Schema`, `Table`, `Column`) and takes `--dataset-id`; `dataplex glossary` loads the business glossary (`Glossary`, `Category`, `BusinessTerm`) and, with `--entry-links` (default on), the `TAGGED_WITH` catalog entry links — run `dataplex schema` first so those edges find their target nodes. Project ID, project number, and location come from `--project-id` / `--project-number` / `--dataplex-location` or the `GCP_PROJECT_ID` / `GCP_PROJECT_NUMBER` / `DATAPLEX_LOCATION` env vars. Both support `--dry-run` and `--json`; embeddings are opt-in via `--embeddings` (default off) and generated through LiteLLM.
- Add `neocarta query-log ingest` CLI command wrapping `QueryLogConnector` to parse a local query-log JSON file (currently the BigQuery export format) into Neo4j. The file path comes from `--query-log-file` or the `QUERY_LOG_FILE` env var; `--source` selects the file format (default: `bigquery`). Supports `--dry-run` and `--json`. This is distinct from `neocarta bigquery logs`, which reads query logs live from the Cloud Logging API. No embeddings are generated, as query-log nodes carry no descriptions.
* Add a MusicBrainz example. The core MusicBrainz schema (12 tables, 86 columns, 11 foreign keys) is described as CSV files under `datasets/musicbrainz/` and loaded with the generic `CSVConnector` — no bespoke connector is needed since MusicBrainz exposes no `INFORMATION_SCHEMA` endpoint. `examples/musicbrainz.py` loads the schema and generates embeddings for Table/Column nodes via `LiteLLMEmbeddingsConnector` (auto-detected to 1536 dims for `text-embedding-3-small`, matching the MCP server's query embeddings so semantic search works unchanged). `agent/musicbrainz_agent.py` is a single-file LangGraph agent that consults the Neocarta MCP schema tools and then queries the live MusicBrainz REST API via a custom `musicbrainz_search` tool. New Make targets: `create-graph-from-musicbrainz`, `create-graph-from-musicbrainz-no-embeddings`, and `musicbrainz-agent`.

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
* Add `neocarta osi ingest` and `neocarta osi export` CLI commands wrapping `OsiConnector`. `osi ingest` loads an OSI YAML semantic model from a local path or HTTP(S) URL (`--spec-source` or the `OSI_SPEC_SOURCE` env var) into Neo4j; embeddings are opt-in via `--embeddings` (default off) and generated through LiteLLM. `osi export` writes an `OsiSemanticModel` from Neo4j back to an OSI YAML file (`--semantic-model-name` or the `OSI_SEMANTIC_MODEL_NAME` env var, plus `--output-path`); an unknown model name exits with a `not_found` error (exit code 3). Both support `--dry-run` and `--json`.

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
