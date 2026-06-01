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
| `OPENAI_API_KEY` | When `--embeddings` | — | OpenAI API key for embedding generation (secret) |
| `GCP_PROJECT_ID` | Yes for `bigquery *` | — | Google Cloud project ID |
| `BIGQUERY_DATASET_ID` | Yes for `bigquery *` | — | Default BigQuery dataset ID |
| `BIGQUERY_REGION` | No | `region-us` | BigQuery region for `INFORMATION_SCHEMA` queries |
| `GOOGLE_APPLICATION_CREDENTIALS` | When running outside a GCP-authenticated shell | — | Path to a GCP service-account JSON (secret) |
| `CSV_DIRECTORY` | For `csv load` | — | Directory containing CSV metadata files |

Secrets are env-only and never logged.

## Global flags

| Flag | Meaning |
|---|---|
| `--json` | Emit JSON on stdout. Automatically enabled when stdout is not a TTY. Also accepted on each subcommand. |
| `--debug` | Verbose diagnostics on stderr. |
| `--no-color` | Strip ANSI colors. `NO_COLOR=1` env also honored. |
| `-v` / `--version` | Print CLI version and exit. |
| `-h` / `--help` | Show help and exit. |

## Commands

### `neocarta bigquery schema`

Extracts BigQuery schema metadata and loads `Database`, `Schema`, `Table`, and `Column` nodes plus their relationships into the Neocarta graph. When `--embeddings` is enabled (default), description embeddings are generated and written back.

- **Flags:**
  - `--project-id TEXT` — GCP project ID. Overrides `GCP_PROJECT_ID`.
  - `--dataset-id TEXT` — BigQuery dataset to ingest. Overrides `BIGQUERY_DATASET_ID`.
  - `--embeddings / --no-embeddings` — Generate embeddings after load. Default: enabled.
  - `--embedding-model TEXT` — OpenAI embedding model (default: `text-embedding-3-small`).
  - `--embedding-dimensions INT` — Embedding vector dimensions (default: `768`).
  - `--dry-run` — Print the planned ingestion as JSON; do not touch Neo4j or BigQuery.
  - `--json` — Emit JSON on stdout.
- **Use when:** ingesting structural metadata from a BigQuery dataset for the first time, or refreshing it after schema changes.

```bash
neocarta bigquery schema --project-id acme-data --dataset-id sales
neocarta bigquery schema --no-embeddings
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
  - `--dry-run` — Print the planned ingestion as JSON; do not touch Neo4j or BigQuery.
  - `--json` — Emit JSON on stdout.
- **Use when:** building lineage and usage context from real query traffic to complement the static schema graph.

```bash
neocarta bigquery logs --dataset-id sales --limit 500
neocarta bigquery logs --start-date 2026-01-01 --end-date 2026-01-31 --json
neocarta bigquery logs --dataset-id sales --include-failed-queries
```

---

### `neocarta csv load`

Loads metadata from a directory of CSV files into the Neocarta graph using `CSVConnector`. Every entity CSV found in the directory is loaded (`Database`, `Schema`, `Table`, `Column`, `Value`, `Query`, and glossary nodes) along with their relationships; files that are not present are skipped. When `--embeddings` is enabled, description embeddings are generated and written back.

- **Flags:**
  - `--csv-directory TEXT` — Directory containing the CSV metadata files. Overrides `CSV_DIRECTORY`.
  - `--embeddings / --no-embeddings` — Generate embeddings after load. Default: disabled.
  - `--embedding-model TEXT` — OpenAI embedding model (default: `text-embedding-3-small`).
  - `--embedding-dimensions INT` — Embedding vector dimensions (default: `768`).
  - `--dry-run` — Print the planned ingestion as JSON; do not touch Neo4j.
  - `--json` — Emit JSON on stdout.
- **Use when:** ingesting curated metadata from CSV files, or loading the bundled sample dataset for local testing.

```bash
neocarta csv load --csv-directory ./datasets/csv
neocarta csv load --csv-directory ./datasets/csv --embeddings
CSV_DIRECTORY=./datasets/csv neocarta csv load --dry-run --json
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
