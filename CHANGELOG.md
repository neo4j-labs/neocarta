# Changelog of neocarta library and MCP server

## Upcoming

### Fixed
* Top-level `--debug` flag now actually prints the chained exception traceback to stderr when a `CLIError` is rendered. It was previously wired up but never read. The flag must precede the subcommand: `neocarta --debug bigquery schema ...`.

### Changed
* BigQuery error envelopes now include `vendor_exception`, `vendor_message`, and `vendor_http_status` in `details`, preserving the original `google.api_core.exceptions.*` class name, server-side message, and HTTP status code in the JSON output. The original exception is still reachable via `__cause__` (and rendered by `--debug`).
* MCP server uses LiteLLM embeddings now instead of OpenAI embeddings. OpenAI embeddings still available via LiteLLM.

### Added
* Add `neocarta.errors` module with a unified `NeocartaError` hierarchy: `ConfigError`, `AuthError`, `StateError`, `RateLimitError`, `OperationTimeoutError`, `ConnectorError`, `ExtractionError`, `TransformError`, `EnrichmentError`, and a `Neo4jError` subtree covering `Neo4jConnectionError`, `LoadError`, `ConstraintCreationError`, and `IndexCreationError`. Each class declares a `code` mapping to an existing CLI exit-code envelope; `RateLimitError` and `OperationTimeoutError` default to `retryable=True`. `StateError` is used for call-order/sequencing failures (e.g. calling `extract_entry_links()` before `extract_glossary_info()`), distinct from `ConfigError` for bad arguments.
* Add `LiteLLMEmbeddingsConnector`. OpenAI embeddings can be generated via this or the original `OpenAIEmbeddingsConnector`. Both now subclass a shared `BaseEmbeddingsConnector` in `neocarta.enrichment.embeddings.base` that owns the batch loop, dimension probing, vector-index creation, and Neo4j read/write; subclasses only override `__init__`, `_create_embedding_sync`, and `_create_embedding_async`.

## v0.5.0

### Added
* Add `performance` optional extra (`pip install neocarta[performance]`) that pulls in `neo4j-rust-ext` for 60–90% faster Neo4j serialisation on bulk loads. Requires Python ≥ 3.11. The extension patches the `neo4j` driver automatically on import — no code changes needed.
* Add `neocarta` CLI (`pip install neocarta[cli]`) exposing `neocarta bigquery schema` and `neocarta bigquery logs` wrappers around the existing connectors. Global `--json` / TTY-detected output, `--no-color`, `--debug`, and `--dry-run` are supported. Connector settings resolve as flag → env var → default; secrets (`NEO4J_PASSWORD`, `OPENAI_API_KEY`, `GOOGLE_APPLICATION_CREDENTIALS`) are env-only. A `.env` file in the working directory is loaded automatically.
* Add `neocarta agent-context` command that emits the full CLI shape (commands, flags, exit codes, recognised env vars) as JSON for AI agents to discover at runtime. The `schema_version` field increments on breaking changes.

## v0.4.0

### Fixed
* Fixed `OpenAIEmbeddingsConnector.run()` and `arun()` closing caller-owned Neo4j drivers after embedding ingestion
* Fix demo data: `business_term_info.csv` had duplicate term identity columns (`term_name` as abbreviation and `name` as full readable name); removed `term_name` abbreviation column and renamed `name` → `term_name`. Updated `column_term_info.csv` and `table_term_info.csv` to reference terms by full readable name to match.
* Fixed query parser reading CTEs as real tables
* Fixed query parser reading `.*` projections as a real column named `*`
* Fixed query parser reading self referential joins as real FKs 

### Changed
* MCP server now probes the target database at startup and registers retrieval tools per label by priority: business-term-bridged hybrid > hybrid (vector + full-text on same label) > vector or full-text alone. Schema-level vector retrieval and catalog tools are registered independently.
* **Breaking:** Renamed vector retrieval MCP tools for consistency with the new full-text / hybrid / business-term-hybrid tool naming. `get_metadata_schema_by_column_semantic_similarity` → `get_context_by_column_vector_search`; `get_metadata_schema_by_table_semantic_similarity` → `get_context_by_table_vector_search`; `get_metadata_schema_by_schema_and_table_semantic_similarity` → `get_context_by_schema_and_table_vector_search`. Cypher helper functions renamed correspondingly.
* `run_agent.py` no longer hardcodes a neocarta tool allowlist; it trusts whatever the neocarta MCP server exposes (since the server self-filters by index inventory) and only allowlists `execute_sql` from the BigQuery MCP server.
* Reorganised `neocarta/_mcp/` cypher into a `cypher/` subpackage (`catalog`, `vector_search`, `full_text_search`, `hybrid_search`) and split MCP tool registrations into a `tools/` subpackage with one module per retrieval strategy.
* **Breaking:** Replaced `OpenAIEmbeddingsConnector` with `LiteLLMEmbeddingsConnector`. Embedding generation now goes through [LiteLLM](https://docs.litellm.ai/), enabling OpenAI, Azure OpenAI, Cohere, Bedrock, Vertex AI, Ollama, HuggingFace, and other providers via a single connector. The constructor no longer takes `client` / `async_client`; provider routing is driven by the `embedding_model` string (e.g. `"text-embedding-3-small"`, `"cohere/embed-english-v3.0"`) and auth comes from provider-specific environment variables or the new `api_key` / `api_base` / `litellm_kwargs` parameters.
* **Breaking:** The `dimensions` constructor parameter is removed. The connector now auto-detects the vector dimension from the model on first embed call (one probe) and creates the Neo4j vector index at that size, so no manual dimension config is required. For non-default sizes (truncation), pass `litellm_kwargs={"dimensions": ...}` and the probe will use it.
* **Breaking:** MCP server settings: `openai_api_key` and `embedding_dimensions` removed. `embedding_model` is the only embedding-related setting. Provider auth (`OPENAI_API_KEY`, `GEMINI_API_KEY`, `AZURE_*`, `AWS_*`, ...) is read directly by LiteLLM from standard env vars. Advanced overrides (LiteLLM Proxy, custom endpoints) move into the connector's `litellm_kwargs` argument.
* `create_openai_embedder` in `neocarta/_mcp/embeddings.py` renamed to `create_embedder`.
* Text2SQL agent chat LLM is now provider-agnostic via `langchain-litellm`. Model is configurable through the `AGENT_MODEL` env var (default `openai/gpt-4o-mini`); any LiteLLM model id is accepted (e.g. `gemini/gemini-2.0-flash`, `anthropic/claude-sonnet-4-5`).

### Added
* Add data model diagram for table views and materialized views
* Add `claude.md` file
* Add `CTE` node to capture CTEs from queries 
* Add `(:Query)-[:DEFINES]->(:CTE)` relationship
* Add full-text search MCP tools: `get_context_by_table_full_text_search`, `get_context_by_column_full_text_search`.
* Add hybrid (vector + full-text on same node) MCP tools: `get_context_by_table_hybrid_search`, `get_context_by_column_hybrid_search`.
* Add business-term-bridged hybrid MCP tools: `get_context_by_table_business_term_hybrid_search`, `get_context_by_column_business_term_hybrid_search`. The full-text branch matches `:BusinessTerm` nodes and bridges to `:Table`/`:Column` nodes via `TAGGED_WITH`.
* Add `__neocarta_graph__` singleton metadata node (`initial_version`, `latest_version`, `create_date`, `last_updated`). Connectors upsert it at the end of every `run()` so the graph carries a record of which neocarta version last wrote to it. The MCP server reads the node at startup and logs a warning when `latest_version` does not match the running server's neocarta version (or when the node is missing).
* Add `litellm` dependency for multi-provider embedding support.
* Add `langchain-litellm` to the `agent` dep group for provider-agnostic agent chat LLM.

## v0.3.0

### Fixed
* Add column data types `["GEOGRAPHY", "JSON", "BIGNUMERIC"]` to skipped list for `Value` node creation. These types will throw an error otherwise.
* Implement `generate_*_id` functions for all ID generation tasks
* Fixed bug where value retrieval would yield empty arrays when all values in column are `NULL`
* Fixed bug where `description='false'` when querying table info due to inaccurate `INFORMATION_SCHEMA.TABLE_OPTIONS` filtering
* Update agent code to use new MCP configuration
* CSV connector `business_term_info.csv` now requires `glossary_name` and `category_name` in addition to `term_name`, ensuring business term IDs are globally unique within a CSV dataset (previously `term_id` alone was not uniquely scoped)
* Dataplex connector `Category` nodes previously used the full GCP resource path as both `id` and `name`; `id` is now a normalised dot-separated slug and `name` is the category slug

### Changed
* Replace `RESOLVES_TO` relationship with `TAGGED_WITH` across RDBMS and LPG data models
* **Breaking:** CSV connector glossary CSV files now use `*_name` columns as required inputs (matching the database hierarchy convention) — `glossary_id` → `glossary_name` in `glossary_info.csv`; `glossary_id`, `category_id` → `glossary_name`, `category_name` in `category_info.csv`; `category_id`, `term_id` → `glossary_name`, `category_name`, `term_name` in `business_term_info.csv`. IDs are now auto-generated as a dot-separated hierarchy from these name columns. Explicit `*_id` columns are still accepted as overrides.

### Added
* Add `TAGGED_WITH` relationship type to `RelationshipType` enum
* Add `TaggedWith` model to RDBMS expanded data model
* Add `extract_entry_links()` to `DataplexExtractor` — retrieves `TAGGED_WITH` links between BigQuery columns/tables and Dataplex glossary terms via the `lookupEntryLinks` REST API
* Add `transform_to_column_tagged_with_relationships()` and `transform_to_table_tagged_with_relationships()` to `DataplexTransformer`
* Add `load_column_tagged_with_relationships()` and `load_table_tagged_with_relationships()` to Neo4j loader
* `DataplexConnector` now creates `(:Column)-[:TAGGED_WITH]->(:BusinessTerm)` and `(:Table)-[:TAGGED_WITH]->(:BusinessTerm)` relationships when both `include_schema` and `include_glossary` are enabled
* Add acme dataset and update example dataset loader function to accomodate ecommerce and acme datasets
* Add optional `resource_path` property to `Glossary`, `Category`, and `BusinessTerm` nodes — intended to hold the full Dataplex resource path when loaded via the Dataplex connector
* Add `generate_glossary_id()`, `generate_category_id()`, and `generate_business_term_id()` to ID generation utilities
* CSV connector now supports loading glossary, category, and business term data; glossary entities follow the same `*_name` column convention as the database hierarchy, with IDs auto-generated as a dot-separated hierarchy (`glossary_name.category_name.term_name`)
* CSV connector now supports `(:Column)-[:TAGGED_WITH]->(:BusinessTerm)` and `(:Table)-[:TAGGED_WITH]->(:BusinessTerm)` relationships via `column_term_info.csv` and `table_term_info.csv`; both files support auto-generated or explicit IDs
* Add sample `column_term_info.csv` and `table_term_info.csv` to the ecommerce dataset
* Dataplex connector now uses `generate_glossary_id()`, `generate_category_id()`, and `generate_business_term_id()` for consistent dot-separated node IDs — IDs produced by the Dataplex and CSV connectors are now interoperable when glossary/category/term slugs match
* Dataplex connector sets `resource_path` on `Glossary`, `Category`, and `BusinessTerm` nodes with the original GCP resource path; glossary `resource_path` is inferred from the category resource path

## v0.2.1

### Fixed
* Remove duplicated docstrings in MCP server

### Added
* Update MCP documentation

## v0.2.0

### Changed
* Move MCP server to `neocarta` library
* Change MCP server name to `neocarta-mcp`
* Update MCP server imports in `eval/` module
* Deduplicate embedding code in MCP server. MCP server now uses `neocarta` embeddings class.
* Update Cypher queries in MCP server to follow same traversal patterns and return similar objects
* Update MCP tool documentation
* Lock `fastmcp` version <3.x

### Added
* Add integration tests for MCP server compatibility with neocarta graph
* Add `get_metadata_schema_by_table_semantic_similarity` tool to MCP server
* Add instructions to MCP server so agents are better able to utilize the tooling

## v0.1.0

Initial release
