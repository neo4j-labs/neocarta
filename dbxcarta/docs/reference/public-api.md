# Public API and version contract

External projects depend on the distribution that matches the capability they use. The public surfaces are:

- **Core:** identifier and path helpers, the `catalog:layer` rule (`resolve_catalogs`), workspace/secret access, the SQL warehouse runner, the preset protocols and `StandardPreset`, the `.env` overlay loader, and the materialize SQL builders
- **Spark:** `SparkIngestSettings`, `run_dbxcarta`, graph contract enums and constants, Databricks identifier/path validators, preset loading, `verify_run`, and the `dbxcarta` / `dbxcarta-ingest` wheel entrypoints
- **Client:** retrieval primitives, SQL parsing and read-only guards, result comparison, `ClientSettings`, and the `dbxcarta.client.eval` harness
- **Materialize:** the `dbxcarta-materialize` wheel entrypoint, the serverless Spark shell that runs core's materialize SQL builders

The `dbxcarta` and `dbxcarta-ingest` commands are registered by
`dbxcarta-spark`, `dbxcarta-client` and `dbxcarta-embed-probe` by
`dbxcarta-client`, `dbxcarta-materialize` by `dbxcarta-materialize`, and
`dbxcarta-submit` by `dbxcarta-submit`. `dbxcarta-core` registers no command.

Removing or renaming a public name above is a breaking change. Adding a new name is additive. Implementation modules below a layer remain internal unless documented here.

## Migration notes

This repository uses a clean boundary cutover. Old top-level imports are deleted instead of re-exported.

| Old path | New path |
|----------|----------|
| `from dbxcarta import run_dbxcarta` | `from dbxcarta.spark import run_dbxcarta` |
| `from dbxcarta import Settings` | `from dbxcarta.spark import SparkIngestSettings` |
| `from dbxcarta import run_client` | `from dbxcarta.client.eval import run_client` |
| `dbxcarta.contract` | `dbxcarta.spark.contract` |
| `dbxcarta.databricks` | `dbxcarta.spark.databricks` for operational helpers; `dbxcarta.client.databricks` for client workflow helpers |
| `dbxcarta.verify` | `dbxcarta.spark.verify` |
| `dbxcarta.ingest.*` | `dbxcarta.spark.ingest.*` |
| `dbxcarta.ingest.pipeline` | `dbxcarta.spark.run` |
| `dbxcarta.client.client` | `dbxcarta.client.eval.run` |
| `dbxcarta.entrypoints.ingest` | `dbxcarta.spark.entrypoint` |
| `dbxcarta.entrypoints.client` | `dbxcarta.client.eval.entrypoint` |
| `dbxcarta.presets` module file | `dbxcarta.core.presets` (protocols + `StandardPreset`) and `dbxcarta.spark.loader` (loader) |

## Client evaluation harness

The validation rationale, the four arms, and why `graph_rag` only justifies the
build pipeline when it beats `schema_dump` at a matched budget, are in
[`architecture.md`](architecture.md#how-we-validate). This section is the cache
mechanics that back that harness.

Each arm generates SQL for all questions in one batched `ai_query` pass,
materialized to a `client_staging_<arm>` Delta table in the ops catalog that
doubles as the cache. A write stamps an `_input_hash` over the ordered endpoint,
arm, and question prompts; an unchanged re-run reads the prior responses and skips
inference, while any change to a prompt, the retrieved context, the question set,
or the endpoint name forces fresh generation. `DBXCARTA_CLIENT_REFRESH=true`
covers the one case the hash cannot see, a model swap behind a stable endpoint
name. The tables use stable names and overwrite mode, so logical size stays at one
run's worth of rows per arm; Delta retains tombstoned files until a `VACUUM`, and
at evaluation scale that is a deliberate non-decision rather than a missing
retention policy.
