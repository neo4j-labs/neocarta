# Neocarta CLI

A command-line interface for driving Neocarta connectors against your data warehouse without writing Python. The CLI is designed to be agent-friendly first and human-friendly second: stable machine-readable output, documented exit codes, non-interactive by default, and an `agent-context` introspection command for AI agents to discover capabilities at runtime.

## Installation

```bash
pip install "neocarta[cli]"
```

The `[cli]` extra adds `click`, `rich`, and `pydantic-settings` on top of the base library.

## Configuration

The CLI reads configuration from environment variables (and a `.env` file in the working directory, loaded automatically). CLI flags override env vars; env vars override built-in defaults.

| Variable | Required | Default | Description |
|---|---|---|---|
| `NEO4J_URI` | Yes | — | Neo4j connection URI (e.g. `bolt://localhost:7687`) |
| `NEO4J_USERNAME` | Yes | — | Neo4j username |
| `NEO4J_PASSWORD` | Yes | — | Neo4j password (secret) |
| `NEO4J_DATABASE` | No | `neo4j` | Neo4j database name |
| `OPENAI_API_KEY` | When `--embeddings` | — | OpenAI API key for embedding generation (secret). Other providers use their own vars (`GEMINI_API_KEY`, `COHERE_API_KEY`, `AZURE_*`, `AWS_*`, …). |
| `EMBEDDING_MODEL` | No | `text-embedding-3-small` | LiteLLM embedding model id (provider prefix optional for OpenAI) |
| `EMBEDDING_DIMENSIONS` | No | auto-detected | Vector dimension for models that support truncation; ignored by models that don't |
| `EMBEDDING_BATCH_SIZE` | No | `100` | Nodes embedded per provider request during ingest runs |
| `GCP_PROJECT_ID` | Yes for `bigquery *` | — | Google Cloud project ID |
| `BIGQUERY_DATASET_ID` | Yes for `bigquery *` | — | Default BigQuery dataset ID |
| `BIGQUERY_REGION` | No | `region-us` | BigQuery region for `INFORMATION_SCHEMA` queries |
| `GCP_PROJECT_NUMBER` | Yes for `dataplex *` | — | Google Cloud project number |
| `DATAPLEX_LOCATION` | Yes for `dataplex *` | — | Dataplex location, e.g. `us` |
| `GOOGLE_APPLICATION_CREDENTIALS` | When running outside a GCP-authenticated shell | — | Path to a GCP service-account JSON (secret) |
| `CSV_DIRECTORY` | For `csv ingest` | — | Directory containing CSV metadata files |
| `OSI_SPEC_SOURCE` | For `osi ingest` | — | Path or URL to an OSI YAML semantic-model spec |
| `OSI_SEMANTIC_MODEL_NAME` | For `osi export` | — | Name of the `OsiSemanticModel` to export |
| `QUERY_LOG_FILE` | For `query-log ingest` | — | Path to a query-log JSON file |
| `JDBC_URL` | Yes for `jdbc schema` | — | JDBC connection URL, e.g. `jdbc:postgresql://host:5432/mydb` |
| `JDBC_DRIVER` | Yes for `jdbc schema` | — | Fully-qualified JDBC driver class, e.g. `org.postgresql.Driver` |
| `JDBC_DRIVER_JAR` | Yes for `jdbc schema` | — | Filesystem path to the JDBC driver JAR |
| `SCHEMACRAWLER_JAR` | Yes for `jdbc schema` | — | Filesystem path or classpath glob to the SchemaCrawler distribution JARs |
| `JDBC_USER` | No | — | Database username |
| `JDBC_PASSWORD` | No | — | Database password (secret). Read only from the env, never a flag. |
| `JDBC_SOURCE_DATABASE_NAME` | No | — | Name for the graph `Database` node; needed when it cannot be derived from `JDBC_URL` (e.g. Oracle SID, SQL Server URLs) |
| `JDBC_PLATFORM` | No | — | Hosting platform for the graph `Database` node, e.g. `AWS_RDS` |
| `JDBC_SERVICE` | No | product reported by SchemaCrawler | Database service/engine for the graph `Database` node |
| `JDBC_TIMEOUT` | No | `120` | Max seconds to wait for the SchemaCrawler subprocess |

Secrets are env-only and never logged.

## Global flags

| Flag | Meaning |
|---|---|
| `--json` | Emit JSON on stdout. Automatically enabled when stdout is not a TTY. Also accepted on each subcommand. |
| `--log-level [DEBUG\|INFO\|WARNING\|ERROR]` | Diagnostics verbosity on stderr. Default: `INFO`. |
| `--debug` | Alias for `--log-level DEBUG`. Verbose diagnostics on stderr. |
| `--no-color` | Strip ANSI colors. `NO_COLOR=1` env also honored. |
| `-v` / `--version` | Print CLI version and exit. |
| `-h` / `--help` | Show help and exit. |

## Commands

### `neocarta bigquery schema`

Extracts BigQuery schema metadata and loads `Database`, `Schema`, `Table`, and `Column` nodes plus their relationships into the Neocarta graph. When `--embeddings` is passed, description embeddings are generated and written back (off by default).

- **Flags:**
  - `--project-id TEXT` — GCP project ID. Overrides `GCP_PROJECT_ID`.
  - `--dataset-id TEXT` — BigQuery dataset to ingest. Overrides `BIGQUERY_DATASET_ID`.
  - `--embeddings / --no-embeddings` — Generate embeddings after load. Default: disabled.
  - `--embedding-model TEXT` — LiteLLM embedding model id (default: `text-embedding-3-small`). Overrides `EMBEDDING_MODEL`.
  - `--embedding-dimensions INT` — Embedding vector dimensions for models that support truncation (default: auto-detected). Overrides `EMBEDDING_DIMENSIONS`.
  - `--embedding-batch-size INT` — Nodes per embedding batch (default: `100`). Overrides `EMBEDDING_BATCH_SIZE`.
  - `--dry-run` — Print the planned ingestion as JSON; do not touch Neo4j or BigQuery.
  - `--json` — Emit JSON on stdout.
- **Use when:** ingesting structural metadata from a BigQuery dataset for the first time, or refreshing it after schema changes.

```bash
neocarta bigquery schema --project-id acme-data --dataset-id sales
neocarta bigquery schema --project-id acme-data --dataset-id sales --embeddings
BIGQUERY_DATASET_ID=sales neocarta bigquery schema --json
```

---

### `neocarta bigquery logs`

Extracts query history from `INFORMATION_SCHEMA.JOBS_BY_PROJECT` and loads `Query` and `CTE` nodes plus the table/column references each query touches.

- **Flags:**
  - `--project-id TEXT` — GCP project ID. Overrides `GCP_PROJECT_ID`.
  - `--dataset-id TEXT` — Dataset whose queries to ingest. Overrides `BIGQUERY_DATASET_ID`.
  - `--region TEXT` — BigQuery region. Overrides `BIGQUERY_REGION`. Default: `region-us`.
  - `--start-date TEXT` — Inclusive start timestamp (ISO 8601). Default: 30 days ago.
  - `--end-date TEXT` — Inclusive end timestamp (ISO 8601). Default: now.
  - `--limit INT` — Maximum number of queries to extract. Default: `100`.
  - `--include-failed-queries` — Retain queries that errored (default: exclude).
  - `--embeddings / --no-embeddings` — Generate embeddings after load. Default: disabled for logs.
  - `--embedding-model TEXT` — LiteLLM embedding model id (default: `text-embedding-3-small`). Overrides `EMBEDDING_MODEL`.
  - `--embedding-dimensions INT` — Embedding vector dimensions for models that support truncation (default: auto-detected). Overrides `EMBEDDING_DIMENSIONS`.
  - `--embedding-batch-size INT` — Nodes per embedding batch (default: `100`). Overrides `EMBEDDING_BATCH_SIZE`.
  - `--dry-run` — Print the planned ingestion as JSON; do not touch Neo4j or BigQuery.
  - `--json` — Emit JSON on stdout.
- **Use when:** building lineage and usage context from real query traffic to complement the static schema graph.

```bash
neocarta bigquery logs --dataset-id sales --limit 500
neocarta bigquery logs --start-date 2026-01-01 --end-date 2026-01-31 --json
neocarta bigquery logs --dataset-id sales --include-failed-queries
```

---

### `neocarta csv ingest`

Loads metadata from a directory of CSV files into the Neocarta graph using `CSVConnector`. Every entity CSV found in the directory is loaded (`Database`, `Schema`, `Table`, `Column`, `Value`, `Query`, and glossary nodes) along with their relationships; files that are not present are skipped. When `--embeddings` is enabled, description embeddings are generated and written back.

- **Flags:**
  - `--csv-directory TEXT` — Directory containing the CSV metadata files. Overrides `CSV_DIRECTORY`.
  - `--embeddings / --no-embeddings` — Generate embeddings after ingest. Default: disabled.
  - `--embedding-model TEXT` — LiteLLM embedding model id (default: `text-embedding-3-small`). Overrides `EMBEDDING_MODEL`.
  - `--embedding-dimensions INT` — Embedding vector dimensions for models that support truncation (default: auto-detected). Overrides `EMBEDDING_DIMENSIONS`.
  - `--embedding-batch-size INT` — Nodes per embedding batch (default: `100`). Overrides `EMBEDDING_BATCH_SIZE`.
  - `--dry-run` — Print the planned ingestion as JSON; do not touch Neo4j.
  - `--json` — Emit JSON on stdout.
- **Use when:** ingesting curated metadata from CSV files, or loading the bundled sample dataset for local testing.

```bash
neocarta csv ingest --csv-directory ./datasets/csv
neocarta csv ingest --csv-directory ./datasets/csv --embeddings
CSV_DIRECTORY=./datasets/csv neocarta csv ingest --dry-run --json
```

---

### `neocarta dataplex schema`

Loads BigQuery schema metadata (`Database`, `Schema`, `Table`, `Column`) plus their relationships from the Dataplex Universal Catalog using `DataplexSchemaConnector`. When `--embeddings` is enabled, `Table` and `Column` description embeddings are generated via LiteLLM and written back.

- **Flags:**
  - `--project-id TEXT` — GCP project ID. Overrides `GCP_PROJECT_ID`.
  - `--project-number TEXT` — GCP project number. Overrides `GCP_PROJECT_NUMBER`.
  - `--dataplex-location TEXT` — Dataplex location, e.g. `us`. Overrides `DATAPLEX_LOCATION`.
  - `--dataset-id TEXT` — BigQuery dataset to ingest. Overrides `BIGQUERY_DATASET_ID`.
  - `--embeddings / --no-embeddings` — Generate embeddings after load (via LiteLLM). Default: disabled.
  - `--embedding-model TEXT` — LiteLLM embedding model id (default: `text-embedding-3-small`). Overrides `EMBEDDING_MODEL`.
  - `--embedding-dimensions INT` — Embedding vector dimensions for models that support truncation (default: auto-detected). Overrides `EMBEDDING_DIMENSIONS`.
  - `--embedding-batch-size INT` — Nodes per embedding batch (default: `100`). Overrides `EMBEDDING_BATCH_SIZE`.
  - `--dry-run` — Print the planned ingestion as JSON; do not touch Neo4j or Dataplex.
  - `--json` — Emit JSON on stdout.
- **Use when:** loading the physical schema of a BigQuery dataset that is catalogued in Dataplex.

```bash
neocarta dataplex schema --project-id my-proj --project-number 123456789 --dataplex-location us --dataset-id sales
neocarta dataplex schema --project-id my-proj --project-number 123456789 --dataplex-location us --dataset-id sales --embeddings
neocarta dataplex schema --dataset-id sales --dry-run --json
```

---

### `neocarta dataplex glossary`

Loads the Dataplex business glossary (`Glossary`, `Category`, `BusinessTerm`) plus their relationships using `DataplexGlossaryConnector`. With `--entry-links` (the default), it also loads catalog↔glossary entry links as `(:Column|:Table)-[:TAGGED_WITH]->(:BusinessTerm)` edges; those attach to existing schema nodes, so run `neocarta dataplex schema` first for the tags to land. Dataset-independent (no `--dataset-id`). When `--embeddings` is enabled, `BusinessTerm` description embeddings are generated via LiteLLM and written back.

- **Flags:**
  - `--project-id TEXT` — GCP project ID. Overrides `GCP_PROJECT_ID`.
  - `--project-number TEXT` — GCP project number. Overrides `GCP_PROJECT_NUMBER`.
  - `--dataplex-location TEXT` — Dataplex location, e.g. `us`. Overrides `DATAPLEX_LOCATION`.
  - `--entry-links / --no-entry-links` — Load `TAGGED_WITH` catalog entry links. Default: enabled. Use `--no-entry-links` to load glossary content only (skips the REST round-trips).
  - `--embeddings / --no-embeddings` — Generate embeddings after load (via LiteLLM). Default: disabled.
  - `--embedding-model TEXT` — LiteLLM embedding model id (default: `text-embedding-3-small`). Overrides `EMBEDDING_MODEL`.
  - `--embedding-dimensions INT` — Embedding vector dimensions for models that support truncation (default: auto-detected). Overrides `EMBEDDING_DIMENSIONS`.
  - `--embedding-batch-size INT` — Nodes per embedding batch (default: `100`). Overrides `EMBEDDING_BATCH_SIZE`.
  - `--dry-run` — Print the planned ingestion as JSON; do not touch Neo4j or Dataplex.
  - `--json` — Emit JSON on stdout.
- **Use when:** loading curated business terminology from a Dataplex glossary and tagging the schema with it (run after `dataplex schema`).

```bash
neocarta dataplex glossary --project-id my-proj --project-number 123456789 --dataplex-location us
neocarta dataplex glossary --project-id my-proj --project-number 123456789 --dataplex-location us --embeddings
neocarta dataplex glossary --no-entry-links --dry-run --json
```

---

### `neocarta jdbc schema`

Extracts relational schema metadata (`Database`, `Schema`, `Table`, `Column` nodes plus foreign-key references) from any JDBC-accessible database and loads it into the Neocarta graph using `JdbcSchemaConnector`. It shells out to SchemaCrawler (Java) to read the catalog, so it works against PostgreSQL, MySQL, SQL Server, Oracle, and other JDBC sources. When `--embeddings` is enabled, description embeddings are generated via LiteLLM and written back.

The database password is read **only** from `JDBC_PASSWORD` (never a flag), so the raw secret never appears in shell history or process arguments.

- **Requires:** Java 11+, a SchemaCrawler distribution JAR, and a JDBC driver JAR on the host. See `neocarta/connectors/jdbc/README.md`.
- **Flags:**
  - `--jdbc-url TEXT` — JDBC connection URL, e.g. `jdbc:postgresql://host:5432/mydb`. Overrides `JDBC_URL`.
  - `--jdbc-driver TEXT` — Fully-qualified JDBC driver class, e.g. `org.postgresql.Driver`. Overrides `JDBC_DRIVER`.
  - `--jdbc-driver-jar TEXT` — Filesystem path to the JDBC driver JAR. Overrides `JDBC_DRIVER_JAR`.
  - `--schemacrawler-jar TEXT` — Path/classpath glob to the SchemaCrawler distribution JARs. Overrides `SCHEMACRAWLER_JAR`.
  - `--db-user TEXT` — Database username. Overrides `JDBC_USER`. (The password is env-only via `JDBC_PASSWORD`.)
  - `--source-database-name TEXT` — Name for the graph `Database` node; required when it cannot be derived from the JDBC URL (e.g. Oracle SID, SQL Server URLs). Overrides `JDBC_SOURCE_DATABASE_NAME`.
  - `--platform TEXT` — Hosting platform for the graph `Database` node, e.g. `AWS_RDS`. Overrides `JDBC_PLATFORM`.
  - `--service TEXT` — Database service/engine for the graph `Database` node (default: the product SchemaCrawler reports). Overrides `JDBC_SERVICE`.
  - `--timeout INT` — Maximum seconds to wait for the SchemaCrawler subprocess (default: `120`). Overrides `JDBC_TIMEOUT`.
  - `--schema TEXT` — Schema name to include; repeatable. Omit to include all schemas.
  - `--embeddings / --no-embeddings` — Generate embeddings after ingest (via LiteLLM). Default: disabled.
  - `--embedding-model TEXT` — LiteLLM embedding model id (default: `text-embedding-3-small`). Overrides `EMBEDDING_MODEL`.
  - `--embedding-dimensions INT` — Embedding vector dimensions for models that support truncation (default: auto-detected). Overrides `EMBEDDING_DIMENSIONS`.
  - `--embedding-batch-size INT` — Nodes per embedding batch (default: `100`). Overrides `EMBEDDING_BATCH_SIZE`.
  - `--dry-run` — Print the planned ingestion as JSON; do not touch Neo4j or the source database.
  - `--json` — Emit JSON on stdout.
- **Use when:** ingesting structural metadata from a relational database that speaks JDBC (PostgreSQL, MySQL, SQL Server, Oracle, …) rather than BigQuery or Dataplex.

```bash
neocarta jdbc schema \
  --jdbc-url jdbc:postgresql://localhost:5432/sales \
  --jdbc-driver org.postgresql.Driver \
  --jdbc-driver-jar ./drivers/postgresql.jar \
  --schemacrawler-jar './schemacrawler/lib/*' \
  --db-user analytics
neocarta jdbc schema --jdbc-url jdbc:postgresql://localhost:5432/sales --schema public --schema sales --embeddings
JDBC_URL=jdbc:postgresql://localhost:5432/sales neocarta jdbc schema --dry-run --json
```

---

### `neocarta osi ingest`

Loads an OSI ([Open Semantic Interchange](https://github.com/open-semantic-interchange/OSI)) YAML semantic model into the Neocarta graph using `OsiConnector`. The spec source may be a local filesystem path or an HTTP(S) URL. Ingests `OsiSemanticModel`, `OsiTable`, `OsiColumn`, `Query`, `Metric`, `Join`, and aspect nodes plus their relationships; synonyms in `ai_context` are upserted as `BusinessTerm` nodes (merged on name, so they dedupe against catalog-derived terms). When `--embeddings` is enabled, `Database`, `Schema`, `Table`, and `Column` description embeddings are generated via LiteLLM and written back.

- **Flags:**
  - `--spec-source TEXT` — Local filesystem path or HTTP(S) URL to the OSI YAML spec. Overrides `OSI_SPEC_SOURCE`.
  - `--embeddings / --no-embeddings` — Generate embeddings after ingest (via LiteLLM). Default: disabled.
  - `--embedding-model TEXT` — LiteLLM embedding model id (default: `text-embedding-3-small`). Overrides `EMBEDDING_MODEL`.
  - `--embedding-dimensions INT` — Embedding vector dimensions for models that support truncation (default: auto-detected). Overrides `EMBEDDING_DIMENSIONS`.
  - `--embedding-batch-size INT` — Nodes per embedding batch (default: `100`). Overrides `EMBEDDING_BATCH_SIZE`.
  - `--dry-run` — Print the planned ingestion as JSON; do not touch Neo4j.
  - `--json` — Emit JSON on stdout.
- **Use when:** loading a semantic model published as an OSI YAML spec, from disk or directly from a URL.

```bash
neocarta osi ingest --spec-source ./datasets/osi/acme_semantic_model.yaml
neocarta osi ingest --spec-source ./datasets/osi/acme_semantic_model.yaml --embeddings
OSI_SPEC_SOURCE=./datasets/osi/acme_semantic_model.yaml neocarta osi ingest --dry-run --json
```

---

### `neocarta osi export`

Exports an OSI semantic model from Neo4j back to an OSI YAML file using `OsiConnector`. Reads the `OsiSemanticModel` with the given name and everything it owns (tables, columns, metrics, joins, aspects) and serializes it to OSI YAML. This is the inverse of `osi ingest`.

- **Flags:**
  - `--semantic-model-name TEXT` — Name of the `OsiSemanticModel` to export. Overrides `OSI_SEMANTIC_MODEL_NAME`.
  - `--output-path TEXT` — Destination path for the exported OSI YAML file. Required.
  - `--dry-run` — Print the planned export as JSON; do not touch Neo4j.
  - `--json` — Emit JSON on stdout.
- **Use when:** round-tripping a semantic model out of the graph, or producing an OSI spec from a model assembled in Neo4j.
- **Exit codes:** a `--semantic-model-name` with no matching model exits `3` (not found).

```bash
neocarta osi export --semantic-model-name acme_corp_model --output-path acme.yaml
OSI_SEMANTIC_MODEL_NAME=acme_corp_model neocarta osi export --output-path acme.yaml
neocarta osi export --semantic-model-name acme_corp_model --output-path acme.yaml --dry-run --json
```

---

### `neocarta query-log ingest`

Parses a local query-log JSON file (currently the BigQuery export format) using `QueryLogConnector` and loads `Query` and `CTE` nodes plus the `Database` / `Schema` / `Table` / `Column` structure and the table/column references each query touches. This is **distinct from `neocarta bigquery logs`**, which reads query logs live from the Cloud Logging API; this command reads a file already on disk. No embeddings are generated (query-log nodes carry no descriptions).

- **Flags:**
  - `--query-log-file TEXT` — Path to the query-log JSON file. Overrides `QUERY_LOG_FILE`.
  - `--source TEXT` — Source/format of the query-log file (default: `bigquery`; the only value supported today).
  - `--dry-run` — Print the planned ingestion as JSON; do not read the file or touch Neo4j.
  - `--json` — Emit JSON on stdout.
- **Use when:** loading queries from an exported BigQuery query-log file (rather than pulling them live via `bigquery logs`).

```bash
neocarta query-log ingest --query-log-file ./query_logs.json
QUERY_LOG_FILE=./query_logs.json neocarta query-log ingest --dry-run --json
```

---

### `neocarta tool <tool>`

Mirrors the [Neocarta MCP server](../_mcp/README.md) tools as read-only CLI commands, one per tool, with the **same names, arguments, and documentation**. Use these to query the semantic graph from a shell or a non-MCP agent without running the server. They reuse the server's Cypher, result models, and embedder, but run synchronously against the CLI's Neo4j driver — so only the `[cli]` install is needed (no `fastmcp` / `[mcp]` extra).

Catalog tools (always available — schema only):

- `neocarta tool list-schemas`
- `neocarta tool list-tables-by-schema --schema-name <schema>`
- `neocarta tool get-full-metadata-schema` *(large payload — debugging / small graphs only)*

Search tools (need the matching index, built by an ingest with `--embeddings`):

- `neocarta tool get-context-by-table-vector-search` / `...-column-vector-search` / `...-schema-and-table-vector-search`
- `neocarta tool get-context-by-table-full-text-search` / `...-column-full-text-search`
- `neocarta tool get-context-by-table-hybrid-search` / `...-column-hybrid-search`
- `neocarta tool get-context-by-table-business-term-hybrid-search` / `...-column-business-term-hybrid-search`

- **Flags:**
  - `--text-content TEXT` — the query string (search tools; required). Mirrors the tool's `text_content`.
  - `--max-tables INT` — maximum tables returned (search tools). Per-tool default matches the MCP tool (10 for table-vector / table-full-text, otherwise 5).
  - `--search-top-k INT` — candidates each index branch returns before ranking (search tools; default 10, or 5 for schema-and-table vector).
  - `--schema-name TEXT` — the schema to list tables for (`list-tables-by-schema`; required).
  - `--json` — emit JSON on stdout.
- **Config:** `NEO4J_*` for every command. The embedding-backed search tools (vector / hybrid / business-term) additionally read `EMBEDDING_MODEL` / `EMBEDDING_DIMENSIONS` and need an embedding-provider key (e.g. `OPENAI_API_KEY`); set the model to match what the graph was embedded with so query and stored vectors agree. Full-text and catalog tools need no provider credentials.
- **Output:** a single top-level key `tool_<tool>` (underscored), e.g. `{"tool_get_context_by_table_vector_search": {"tool": ..., "text_content": ..., "max_tables": ..., "search_top_k": ..., "count": N, "results": [...]}}`. `results` is the same `TableContext` shape (table + matched columns + types + example values + foreign-key references + scores) the MCP server returns; `list-schemas` / `list-tables-by-schema` return their raw records, while `get-full-metadata-schema` returns the `TableContext` shape (mirroring the server's `get_full_metadata_schema`). For `list-tables-by-schema`, `count` is the number of tables (not the single aggregated row).
- **Exit codes:** missing required input → `2` (usage error); a graph missing the required vector/full-text index → `3` (not found, with a suggestion to ingest with `--embeddings`); a failed query embedding (bad/missing provider key or model) → `8` (upstream error).
- **Use when:** scripting metadata retrieval, debugging what the MCP server would return, or giving a non-MCP agent the same retrieval surface.

> Unlike the MCP server — which probes the graph and registers a single best search tool per label — the CLI exposes **all** tools statically (so `agent-context` always lists them); a tool whose index is absent simply exits `3` at call time.

```bash
neocarta tool list-schemas --json
neocarta tool list-tables-by-schema --schema-name sales --json
neocarta tool get-context-by-table-vector-search --text-content "customer orders" --max-tables 5 --json
neocarta tool get-context-by-column-full-text-search --text-content "customer_id" --json
```

---

### `neocarta agent-context`

Emits the full CLI shape as a single JSON document on stdout. Intended for AI agents to discover commands, flags, exit codes, and recognized env vars without scraping `--help`.

- **Input:** none
- **Output:** JSON with `schema_version`, `cli_version`, `commands`, `exit_codes`, `error_codes`, `env_vars`, `output_formats`
- **Use when:** an agent needs to plan a call without prior knowledge of the CLI surface. `schema_version` increments on breaking changes; field names are part of the public contract.

```bash
neocarta agent-context | jq '.commands.bigquery.subcommands.schema.flags'
```

---

## Output discipline

- **stdout** carries the result. When `--json` is set (or stdout is not a TTY), output is a single top-level JSON object. When stdout is a TTY, output is a short human-readable line or table.
- **stderr** carries diagnostics, progress, and errors. It never contains the result.
- ANSI escape codes are suppressed when stdout is not a TTY (unless `FORCE_COLOR=1`). `NO_COLOR=1` always strips colors.

## Exit codes

The CLI uses a closed exit-code map. Renaming a code's meaning is a breaking change.

| Code | Meaning |
|---|---|
| `0` | Success — including empty results |
| `1` | General/unexpected failure |
| `2` | Usage error (bad flag, missing required input) |
| `3` | Resource not found |
| `4` | Permission denied / auth required |
| `5` | Conflict (resource already exists) |
| `6` | Validation error (input rejected) |
| `7` | Rate limited / quota exceeded |
| `8` | Upstream/transient service failure |
| `124` | Timeout |

On error in `--json` mode the structured envelope is also emitted to stdout under `{"error": {...}}` so agents see it without parsing stderr:

```json
{
  "error": {
    "code": "usage_error",
    "exit_code": 2,
    "message": "Missing required setting: --project-id.",
    "retryable": false,
    "suggestion": "Pass --project-id on the command line or set GCP_PROJECT_ID."
  }
}
```

## Notes for agent integration

- Call `neocarta agent-context` once to discover the command tree before issuing any other command. The output is bounded and safe to cache for the duration of a session.
- The CLI is non-interactive by default and never prompts when stdin is not a TTY — it fails fast with exit code `2` and a structured error.
- Every write-capable command supports `--dry-run`, which performs zero side effects and prints the planned action as JSON. Use it to validate inputs before committing.
