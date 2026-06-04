# dbxcarta: Neo4j Semantic Layer for Databricks Unity Catalog

*Inspired by [neocarta](https://github.com/neo4j-field/neocarta).*

## Overview

Unity Catalog publishes tables, columns, and declared constraints but not
meaning: which tables sit near a question, which relationships exist beyond
declared foreign keys, which medallion layer holds the trustworthy version of an
entity. dbxcarta builds a semantic layer over Unity Catalog in Neo4j that turns
that flat metadata into a graph a question can traverse, where similarity is an
embedding distance, a relationship is a confidence-scored edge, and every table
carries its medallion layer. Text2SQL agents, MCP tools, and schema-aware RAG
pipelines query the graph at runtime to retrieve the slice they need before
generating SQL.

```
┌──────────────────────┐   ┌───────────────┐   ┌──────────────────────┐   ┌──────────────────────┐   ┌──────────────────────┐   ┌───────────────┐
│ dbxcarta-materialize │──►│ Unity Catalog │──►│ dbxcarta-spark       │──►│ Neo4j semantic layer │──►│ dbxcarta-client      │──►│ SQL / answer  │
│ blueprint to tables  │   │ flat metadata │   │ build: extract,      │   │ typed nodes, vectors,│   │ query: embed,        │   │ generated     │
│ (seeds example data) │   │               │   │ embed, infer FKs     │   │ confidence-scored FKs│   │ vector + graph fetch │   │ result        │
└──────────────────────┘   └───────────────┘   └──────────────────────┘   └──────────────────────┘   └──────────────────────┘   └───────────────┘
```

The leftmost stage applies only to the bundled examples: `dbxcarta-materialize`
seeds their demo tables into Unity Catalog from a committed blueprint. Against
your own catalog the tables already exist, so the flow starts at Unity Catalog
and `dbxcarta-materialize` is not used.

Two packages are dbxcarta: `dbxcarta-core` and `dbxcarta-spark` build the
semantic layer, and that is the product. The rest support it. `dbxcarta-submit`
deploys the pipeline as a Databricks job, and `dbxcarta-client`,
`dbxcarta-materialize`, and the bundled `examples/` evaluate and demonstrate the
layer. To map your own catalog you need only core and spark, plus submit to run
them.

The semantic-layer thesis, the three storage planes (data, semantic layer, ops),
and the validation model are documented in
[`docs/reference/architecture.md`](docs/reference/architecture.md), the
canonical architecture reference.

## Packages

dbxcarta is five packages in three tiers over a shared, Spark-free core. The
product is `dbxcarta-core` and `dbxcarta-spark`: core is the foundation and spark
builds the semantic layer. `dbxcarta-submit` is the operator-local CLI that
builds, uploads, and submits the jobs, and you need it to run the real pipeline.
`dbxcarta-client`, `dbxcarta-materialize`, and the bundled `examples/` are the
evaluation and demo tier that proves and showcases the layer. The siblings each
depend on core but never on one another, and there is no top-level `dbxcarta`
import surface, so library consumers import the layer they need.

```
┌───────────────────────────────────────────────────────────────────────────┐
│ examples/   finance-genie · schemapile · dense-schema                       │
│ overlay env + preset object                    depend on → client, core     │
└───────────────────────────────────────────────────────────────────────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        ▼                            ▼                            ▼
┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
│ dbxcarta-spark       │  │ dbxcarta-client      │  │ dbxcarta-materialize │
│ UC ingest to Neo4j   │  │ retrieval + eval     │  │ build demo tables    │
│ +pyspark +neo4j      │  │ +requests            │  │ +pyspark (shell)     │
└──────────────────────┘  └──────────────────────┘  └──────────────────────┘
        │                            │                            │
        └────────────────────────────┼────────────────────────────┘
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ dbxcarta-core      Spark-free shared foundation · databricks-sdk only       │
│ identifiers · catalogs · workspace · executor · presets · env ·             │
│ materialize (pure SQL builders) · questions · config · volume_io            │
└───────────────────────────────────────────────────────────────────────────┘

   dbxcarta-submit   operator CLI · depends on core + databricks-job-runner
                     builds wheels, uploads, and submits the spark / client /
                     materialize jobs. Runs locally; never on the cluster.
```

**The product**: builds the semantic layer; the two packages you need for your own catalog.

| Distribution | Capability | Import path | Console script |
|--------------|------------|-------------|----------------|
| `dbxcarta-core` | The shared foundation every other package builds on: common helpers for naming, config, secrets, and running SQL. Depends only on the Databricks SDK. | `dbxcarta.core` | — |
| `dbxcarta-spark` | Reads Unity Catalog metadata, embeds it, infers foreign keys, and writes the semantic-layer graph into Neo4j. | `dbxcarta.spark` | `dbxcarta`, `dbxcarta-ingest` |

**Operator tooling**: runs the pipeline on Databricks.

| Distribution | Capability | Import path | Console script |
|--------------|------------|-------------|----------------|
| `dbxcarta-submit` | The command you run on your own machine to build, upload, and launch the Databricks jobs. | `dbxcarta.submit` | `dbxcarta-submit` |

**Evaluation & demo**: prove and showcase the layer; not needed to build it for your own catalog.

| Distribution | Capability | Import path | Console script |
|--------------|------------|-------------|----------------|
| `dbxcarta-client` | Queries the finished graph to retrieve schema context and scores how well the semantic layer helps Text2SQL. | `dbxcarta.client` | `dbxcarta-client`, `dbxcarta-embed-probe` |
| `dbxcarta-materialize` | A Databricks job that creates the example demo tables from a saved blueprint. | `dbxcarta.materialize` | `dbxcarta-materialize` |

**Which package do I need?** To map your own catalog, install `dbxcarta-core` and
`dbxcarta-spark` and run them with `dbxcarta-submit`. The rest are for evaluation
and demos. New here? Jump to the [Quickstart](#quickstart-demo-catalog).

**Layer responsibilities:**

*The product*

- **Core** is the shared bottom layer every other package builds on. It provides the common building blocks for naming and paths, reading config and secrets, running SQL, and loading settings. It depends only on the Databricks SDK, never Spark, Neo4j, or the job runner. The boundaries are enforced by `tests/boundary/test_import_boundaries.py`.
- **Spark** reads Unity Catalog and builds the Neo4j semantic layer: extract, embed, infer foreign keys, write the graph, and verify it. It provides the `dbxcarta` command for verify and preset.

*Operator tooling*

- **Submit** is the command you run on your own machine to build, upload, and submit Databricks jobs. It is the only layer that touches the job runner, and it never runs on the cluster.

*Evaluation & demo*

- **Client** queries the finished graph to retrieve schema context and runs the Text2SQL evaluation that proves the layer earns its place.
- **Materialize** is a Databricks job that creates the example demo tables from a saved blueprint.

The component-level breakdown of each layer is in [`docs/reference/architecture.md`](docs/reference/architecture.md#packages-and-layer-responsibilities).

This repository uses a clean boundary cutover. Old top-level imports are deleted
instead of re-exported; see the migration table in
[`docs/reference/public-api.md`](docs/reference/public-api.md#migration-notes).

## dbxcarta-spark

The Spark package owns the concrete Unity Catalog ingest implementation, the
graph contract, verification, Databricks validators, the preset capability
protocols, and the `dbxcarta` domain CLI for verify and preset. It builds the
Neo4j semantic layer.

**What the build pipeline does:**

- Extracts Unity Catalog metadata across one or more catalogs: table names, column descriptions, comments, and sampled values
- Tags every table with its medallion layer from the `catalog:layer` entries in `DBXCARTA_CATALOGS`; dbxcarta reads only the silver and gold layers, folding them into one graph
- Embeds each piece using a Databricks foundation model
- Discovers foreign keys from declared constraints plus metadata and semantic inference, each edge scored by confidence
- Writes the result to Neo4j as typed nodes with vector properties

### Graph schema

The build pipeline writes a stable typed contract the client traverses: nodes
`Database`, `Schema`, `Table`, `Column`, and `Value`, connected by `HAS_SCHEMA`,
`HAS_TABLE`, `HAS_COLUMN`, `HAS_VALUE`, and confidence-scored `REFERENCES` edges
between columns. Each node carries a dotted catalog-qualified `id`, a
`description`, and an `embedding` where applicable; `Table` nodes also carry a
`layer` tier under graph contract v1.1. The full contract, including identifier
generation, per-node properties, embeddings, and versioning, is in
[`docs/schema/SCHEMA.md`](docs/schema/SCHEMA.md).

![dbxcarta Graph Schema](docs/assets/graph-schema.png)

### Build time: pipeline writes the graph

Unity Catalog metadata flows through a single Spark job: preflight checks grants
and config, extract unions `information_schema` into DataFrames, transform shapes
typed graph rows, embed calls `ai_query` per label, a Delta staging table
materializes the enriched rows once, then `MERGE` writes nodes and relationships
into Neo4j and refreshes the vector indexes. The stage-by-stage walkthrough is in
[`docs/reference/pipeline.md`](docs/reference/pipeline.md).

### Use as a library

Code running with Databricks Spark access can construct `SparkIngestSettings` and call the ingest implementation directly:

```python
from dbxcarta.spark import SparkIngestSettings, run_dbxcarta

settings = SparkIngestSettings(
    dbxcarta_catalog="analytics_silver",
    dbxcarta_catalogs="analytics_silver:silver,analytics_gold:gold",
    dbxcarta_schemas="finance,customer_success",
    dbxcarta_summary_volume="/Volumes/analytics/ops/dbxcarta/summaries",
    dbxcarta_summary_table="analytics_ops.dbxcarta.dbxcarta_runs",
    dbxcarta_include_embeddings_tables=True,
    dbxcarta_include_embeddings_columns=True,
)

run_dbxcarta(settings=settings)
```

`dbxcarta_catalog` is the single anchor catalog used for preflight, verify, and ops provisioning. `dbxcarta_catalogs` lists every catalog folded into one graph and is the default model: a build normally spans several catalogs. A single-catalog build remains fully supported; leave `dbxcarta_catalogs` blank and it falls back to the anchor catalog. Each `dbxcarta_catalogs` entry is `catalog` or `catalog:layer`; the optional `:layer` suffix sets the `Table.layer` property, and an entry with no suffix yields a null layer. The summary table's catalog and schema determine the ops catalog, which is kept separate from the data catalogs being mapped.

The no-argument form, `run_dbxcarta()`, is the Databricks wheel entrypoint. It loads `SparkIngestSettings` from environment variables and runs the same pipeline.

### Design principles

Everything runs inside Databricks: no external orchestrators, no local execution,
no service accounts. The build is a single Spark submission, embeds each row once
via a materialize-once Delta staging step, and writes Neo4j behind a fail-closed
boundary. That architectural rationale is in
[`docs/reference/architecture.md`](docs/reference/architecture.md#building-the-layer).
The operational rules, Spark and Neo4j connector tuning, preflight grant checks,
secret handling, metadata-source scope, and run observability, are in
[`docs/reference/best-practices.md`](docs/reference/best-practices.md).

## dbxcarta-client: validation harness

The client package owns retrieval primitives and the Text2SQL eval harness. It
queries the Neo4j semantic layer the Spark package built.

### Query time: client retrieves schema context

A client embeds a user question, runs a vector similarity search to find the most
relevant `Table`, `Column`, and `Value` nodes, then traverses `HAS_COLUMN`,
`HAS_VALUE`, and `REFERENCES` edges to expand that seed into a full schema
subgraph before the LLM call. The combination delivers semantic relevance and
structural completeness in one retrieval step. The query-time and validation
walkthrough is in
[`docs/reference/architecture.md`](docs/reference/architecture.md#how-we-validate).

### Demo client details

The client is a batch evaluation job that proves the semantic layer earns its
place. It runs each question through up to four arms selected by
`DBXCARTA_CLIENT_ARMS`, scored the same way (parsed, executed, non-empty, matched
against a reference result):

- **`reference`** executes the ground-truth SQL to establish the correct result.
- **`no_context`** gives the model only the catalog name, the floor.
- **`schema_dump`** pastes a bounded schema pulled from the graph, capped to a token-matched budget so it is a real control rather than a paste-everything strawman.
- **`graph_rag`** is the semantic layer in use: vector-seed plus confidence-ranked `REFERENCES` expansion. It justifies the build pipeline only if it beats `schema_dump` at the matched budget and both clear `no_context`.

The arms cache generation in the ops catalog so unchanged re-runs skip inference.
The cache layout and refresh controls are in
[`docs/reference/public-api.md`](docs/reference/public-api.md#client-evaluation-harness),
and the validation rationale is in
[`docs/reference/architecture.md`](docs/reference/architecture.md#how-we-validate).

In the quickstart the client runs the `graph_rag` arm against
`tests/fixtures/demo_questions.json` after that file is uploaded to
`DATABRICKS_VOLUME_PATH`. The question set exercises cross-schema joins,
self-referential FKs, composite FK paths, and intra-schema event analytics. For
your own catalog, upload a replacement questions JSON file and point
`DBXCARTA_CLIENT_QUESTIONS` at it.

## Presets and examples

### What a preset is

A **preset** is a reusable configuration adapter published by an external
package and referenced by an import-path spec like `your_pkg.module:preset`. The
left side is a Python module path; the right side is the name of the `preset`
object within that module. The CLI resolves this at runtime by importing the
module and reading the object. A preset bundles three things together:

1. **Environment overlay:** the set of environment variables needed to run dbxcarta against a specific upstream project or schema
2. **Readiness check** (optional): logic to verify each ingested catalog holds a data schema before running ingest
3. **Question upload** (optional): logic to push a demo question set to the configured UC Volume

**Why use a preset?**

Without a preset, every developer running dbxcarta against the same upstream project (such as Finance Genie) must manually collect and maintain the correct environment variables. A preset packages that knowledge once and makes it repeatable. Install the example package, then reference the preset by import path instead of managing env vars by hand.

The preset protocols and the shared `StandardPreset` live in
`dbxcarta.core.presets`; the `dbxcarta.spark.loader` resolves a preset from its
import-path spec. Neither requires core or Spark to depend on the client
runtime.

**The preset interface:**

Per-example config lives in the committed `dbxcarta-overlay.env`, not in the
preset, so the preset carries only behavior. Both capabilities are optional.

| Method | CLI flag | Purpose |
|--------|----------|---------|
| `readiness(ws, warehouse_id)` | `--check-ready` | Checks that each ingested catalog holds a data schema |
| `upload_questions(ws)` | `--upload-questions` | Uploads the preset's demo question set to the configured UC Volume |

### Available examples

Companion examples show how to package reusable configuration and demo data for
known upstream projects. Each example is its own Python package that depends on
the relevant dbxcarta distributions as normal pip dependencies and exposes a
module-level `preset` object. Core provides the preset protocols and the shared
`StandardPreset`; the Spark package provides the loader. Each example constructs
`StandardPreset` with its bundled question set.

#### Finance Genie

[**Follow the Finance Genie Quick Start →**](examples/finance-genie/README.md#quick-start)

- **Layout:** two-catalog medallion. Finance Genie writes curated business tables to silver and graph-enriched features to gold, named `graph-enriched-finance-silver` and `-gold`.
- **Graph:** dbxcarta folds both catalogs into one Neo4j semantic layer via `DBXCARTA_CATALOGS`, tagging each table's tier from the `:layer` suffix on each entry.
- **Ops catalog:** run summaries and the generation cache land in a separate `dbxcarta-catalog`.

#### SchemaPile

[**Follow the SchemaPile Quick Start →**](examples/schemapile/README.md#quick-start)

- **Source:** a reproducible slice of [SchemaPile](https://github.com/amsterdata/schemapile) materialized as Delta tables in a dedicated catalog.
- **Schema list:** `schemapile_lakehouse` is a dedicated, data-only catalog, so a blank `DBXCARTA_SCHEMAS` auto-discovers the materialized schemas.
- **Questions:** a SQL-validated question set is generated.
- **Preset:** exposes `dbxcarta_schemapile_example:preset`.

#### Dense schema

[**Follow the Dense Schema Quick Start →**](examples/dense-schema/README.md#quick-start)

- **Purpose:** stress-test schema-context retrieval against dense schema context.
- **Schema:** a synthetic single schema of 500 or 1000 tables.
- **Catalog:** reuses the SchemaPile lakehouse catalog.
- **Preset:** exposes `dbxcarta_dense_schema_example:preset`.

### Preset workflow

Every example exposes the same preset and follows the same steps. The
per-example config lives in the committed `dbxcarta-overlay.env`, so select that
overlay once and every preset command picks it up.

1. Install the example package alongside dbxcarta:
   ```bash
   uv pip install -e examples/finance-genie/
   ```

2. Select the example's overlay (the single source of per-example config):
   ```bash
   export DBXCARTA_ENV_FILE=examples/finance-genie/dbxcarta-overlay.env
   ```

3. Check readiness, which confirms each ingested catalog holds a data schema:
   ```bash
   uv run dbxcarta preset dbxcarta_finance_genie_example:preset --check-ready
   ```

4. Upload the preset's demo question set to the configured UC Volume:
   ```bash
   uv run dbxcarta preset dbxcarta_finance_genie_example:preset --upload-questions
   ```

**Generated examples** (schemapile, dense-schema) follow the identical steps;
materialize the source data first so readiness sees a data schema. Swap the
package name and overlay path:

```bash
uv pip install -e examples/schemapile/
export DBXCARTA_ENV_FILE=examples/schemapile/dbxcarta-overlay.env
uv run dbxcarta preset dbxcarta_schemapile_example:preset --check-ready

uv pip install -e examples/dense-schema/
export DBXCARTA_ENV_FILE=examples/dense-schema/dbxcarta-overlay.env
uv run dbxcarta preset dbxcarta_dense_schema_example:preset --check-ready
```

See each example's README for its full setup flow.

## Quickstart: demo catalog

This path creates the demo Unity Catalog schemas, builds the Neo4j semantic layer, then runs the demo client against that graph.

### 1. Configure the project

```bash
uv sync
cp .env.sample .env
```

Open `.env` and replace the placeholders. Keep the demo defaults already organized in `.env.sample`:

- The four `dbxcarta_test_*` schemas
- Table and column embeddings enabled
- Values enabled
- `DBXCARTA_CLIENT_ARMS=graph_rag`
- `DBXCARTA_CLIENT_QUESTIONS` pointing at the UC Volume copy of `demo_questions.json`

Use an existing UC catalog, schema, and volume, or create them if your principal has permission:

```bash
uv run dbxcarta-submit schema create <catalog>.<schema>
uv run dbxcarta-submit volume create <catalog>.<schema>.<volume>
```

Create the Neo4j secrets in Databricks. These keys are read from the secret scope at job runtime.

```bash
./setup_secrets.sh --profile <your-profile>
```

If the Neo4j database already has dbxcarta data, clear it before the first demo run so constraints and vector indexes are created cleanly:

```cypher
MATCH (n) DETACH DELETE n;
```

### 2. Create the demo source schemas

`scripts/run_demo.py` uses `DBXCARTA_CATALOG`, `DATABRICKS_WAREHOUSE_ID`, and `DATABRICKS_VOLUME_PATH` from `.env`. It creates and populates the demo source schemas in Unity Catalog.

This quickstart uses the built-in demo catalog, created locally through the SQL warehouse by `run_demo.py`. The bundled examples (finance-genie, schemapile, dense-schema) instead seed their tables with the serverless `dbxcarta-submit materialize` job; see each example's README.

```bash
uv run python scripts/run_demo.py
```

### 3. Build the semantic layer

Upload the package wheel, upload the demo questions file to the configured UC Volume, then submit the installed wheel's ingest entrypoint.

```bash
uv run dbxcarta-submit publish-wheels
uv run dbxcarta-submit upload --data tests/fixtures
uv run dbxcarta-submit submit-entrypoint ingest
```

The ingest run should finish with `status=success`. It:

- Writes the graph to Neo4j
- Writes JSON run output under `DBXCARTA_SUMMARY_VOLUME`
- Appends a row to `DBXCARTA_SUMMARY_TABLE`

### 4. Run the demo client

The demo client:

- Embeds each question
- Retrieves context from the Neo4j semantic layer
- Asks the configured chat endpoint for SQL
- Executes the SQL on the warehouse
- Writes a client run summary

```bash
uv run dbxcarta-submit submit-entrypoint client
```

Check the job output for per-arm `executed` and `non_empty` rates:

```bash
uv run dbxcarta-submit logs <run_id>
```

### 5. Verify and clean up

Run local tests:

```bash
uv run pytest
```

Run live integration tests after a successful ingest:

```bash
uv run pytest tests/integration -m live
```

Re-run structural verification against the most recent successful run summary:

```bash
uv run dbxcarta verify
```

Remove the demo schemas when you are done:

```bash
uv run python scripts/run_demo.py --teardown
```

## Configuration

All pipeline and client behavior is controlled by `.env`. Copy `.env.sample`, fill in the placeholders, and use the comments in that file as the configuration reference. The sample is organized by:

- Databricks auth
- Workspace locations
- Compute
- Secrets
- Unity Catalog scope
- Run artifacts
- Embeddings
- Neo4j write tuning
- Client settings

## Automated end-to-end test

`scripts/run_autotest.py` is a self-contained harness that:

- Provisions a known fixture schema in Unity Catalog
- Runs the full pipeline against it
- Asserts the resulting `RunSummary` JSON meets expected thresholds
- Produces a dated JSON result file in the configured volume
- Exits non-zero on any failure

**Prerequisites** — the following must be set in `.env` (or the environment):

| Variable | Purpose |
|----------|---------|
| `DATABRICKS_PROFILE` | Databricks CLI profile for auth |
| `DATABRICKS_CLUSTER_ID` or `DATABRICKS_COMPUTE_MODE=serverless` | Compute for the pipeline job |
| `DATABRICKS_WAREHOUSE_ID` | SQL warehouse used for schema setup |
| `DBXCARTA_CATALOG` | The autotest provisions its fixture schemas and ops artifacts in one catalog and requires `dbxcarta-catalog`. This is the autotest harness's own single-catalog convention, not the general model: a normal build separates data catalogs from the ops catalog (see [`docs/reference/architecture.md`](docs/reference/architecture.md)). |
| `DBXCARTA_SUMMARY_VOLUME` | UC Volume path where `RunSummary` JSON and autotest results are written |

**Run:**

```bash
uv run python scripts/run_autotest.py
```

**Phases:**

| Phase | What it does |
|-------|-------------|
| 0 — Preflight | Verifies workspace connectivity and that the SQL warehouse is reachable |
| 1 — Unit test gate | Runs the fast offline pytest suite; aborts if any test fails |
| 2 — Schema setup | Tears down and recreates the fixture schemas (`dbxcarta_test_{sales,inventory,hr,events}`) in `dbxcarta-catalog` using `tests/fixtures/setup_test_catalog.sql` |
| 3 — Ingest run | Builds and uploads the wheel, submits `dbxcarta-ingest`, waits for `SUCCESS`, and downloads the `RunSummary` JSON |
| 4 — Assertions | Validates the `RunSummary`: `status=success`, `error=null`, `schemas >= 4`, `tables >= 19`, `fk_declared >= 16`, `fk_edges >= 16`, `neo4j_counts` non-empty |
| 5 — Output JSON | Writes `autotest_results_<ts>.json` to `DBXCARTA_SUMMARY_VOLUME/autotest/` and locally to `outputs/` (git-ignored) |

The fixture covers all the structural edge cases:

- **Cross-schema FKs:** sales to hr, sales to inventory
- **Self-referential FK:** `employees.manager_id`
- **Composite PK / associative table:** `product_suppliers`
- **Complex column types:** `STRUCT`, `ARRAY`, `MAP`, `VARIANT`, `BINARY`
- **External schema** (`dbxcarta_test_external`): requires a UC Volume path; excluded from ingest but included in teardown

**Notes:**

- The harness locates the `RunSummary` via a before/after volume diff. `DATABRICKS_JOB_RUN_ID` is not set for one-time `runs.submit()` jobs, so the file is always written as `dbxcarta_local_<ts>.json`.
- Schema setup and teardown are idempotent; re-running always starts from a clean state.
- Unit tests run with `--ignore=tests/integration` to exclude slow live-catalog suites.
- Results are also written locally to `outputs/autotest_results_<ts>.json` (git-ignored) for quick inspection without going back to the volume.

## dbxcarta-submit: operator tooling

These operator commands are provided by the `dbxcarta-submit` package, a thin CLI wrapper around `databricks-job-runner` that handles upload, submit, and cleanup. It depends on `dbxcarta-core`, runs on the operator's machine, and is never installed on the cluster. No other package depends on the job runner.

### Supply-chain checks

Run the local supply-chain checks before submitting a changed package to Databricks:

```bash
uv lock --check
uv sync --frozen --group test --all-packages
uv run pytest
rm -rf dist
uv build --all-packages
uv run python scripts/security/artifact_audit.py inspect dist
uv run python scripts/security/artifact_audit.py provenance dist \
  --output dist/supply-chain-provenance.json
```

The provenance file records:

- The source commit
- Lockfile hash
- Package version
- SHA256 hashes for built artifacts

Treat it as audit evidence for the reviewed artifacts.

**`bootstrap`**

Creates the catalog, schema, and volume named by the selected overlay's `DATABRICKS_VOLUME_PATH` (`CREATE ... IF NOT EXISTS`), running locally against a SQL warehouse. Idempotent, so it is the first step of every `e2e-<example>-ingest` make target and a no-op on later runs; needs `DATABRICKS_WAREHOUSE_ID` and operator privilege. `--dry-run` prints the three names (and refuses a protected catalog) without touching the workspace.

**`teardown`**

Drops the catalog or schema named by the overlay's `DBXCARTA_TEARDOWN_TARGET` (`schema:<catalog>.<schema>` or `catalog:<catalog>`, dropped with `CASCADE`). Destructive and never automatic: it requires `--yes-i-mean-it`, and without it — or under `--dry-run` — only prints what it would drop. A shared protected-name blocklist guards both commands, so neither can name a system catalog. Run by hand via `make e2e-<example>-teardown`.

**`publish-wheels`**

Builds each dbxcarta wheel, bumps the patch version, uploads the wheels to `DATABRICKS_VOLUME_PATH/wheels/`, and ships the cluster bootstrap script. Re-run whenever `packages/dbxcarta-*/src/` changes.

**`upload`** (generic, passed through to `databricks-job-runner`)
- `--all` — copies every `scripts/*.py` to the workspace. Re-run whenever `scripts/` changes.
- `--data DIR` — uploads a data directory to the UC volume.

**`submit <script>`**

The script name is relative to `scripts/`. Scripts named `run_dbxcarta*` auto-attach the latest uploaded wheel. All non-Databricks `.env` variables are forwarded to the job.

Supply-chain note: `publish-wheels` currently combines version bumping, building, and UC Volume upload. For reviewed releases, prefer a CI-built wheel and provenance manifest as the artifact of record. A future hardening step should make Databricks submission select a wheel by explicit version or hash instead of by latest local wheel mtime.

- `--upload` — uploads `scripts/*.py` before submitting, replacing a separate `upload --all` step.
- `--no-wait` — returns immediately with the run ID.
- `--compute {cluster,serverless}` — overrides `DATABRICKS_COMPUTE_MODE` for this run.

### Clean up a project

Each integration writes its run artifacts to an ops plane: a run summary table, the per-arm client staging/retrieval tables, and a volume holding `runs/`, `staging/`, and the embedding-reuse `ledger/`. To reset one integration, point `scripts/clean-dbxcarta.py` at that integration's overlay env file. The ops location is read from `DBXCARTA_SUMMARY_TABLE` and `DATABRICKS_VOLUME_PATH` in the overlay, so the same script cleans any project:

```bash
uv run scripts/clean-dbxcarta.py \
  --profile aws-partner-rk \
  --env-file examples/finance-genie/dbxcarta-overlay.env
```

It first reads the workspace and prints every table and volume path it will delete, then waits for a `y/n` answer before touching anything. It drops the ops tables (`dbxcarta_run_summary`, `client_retrieval`, every `client_staging_*`) and empties the ops volume contents, including the embedding ledger. The schema and the volume object itself are kept. Pass `-y`/`--yes` to skip the prompt in automation, or `--warehouse-id` to override warehouse selection.

## Public API and version contract

External projects depend on the distribution that matches the capability they
use. The per-distribution public surfaces, the registered commands, the
breaking-change policy, and the old-to-new import migration table are in
[`docs/reference/public-api.md`](docs/reference/public-api.md).

## Known operational gotchas

Operational lessons from running the pipeline, including why dropping a data
catalog on a Default-Storage account is not round-trippable through the tooling,
are in
[`docs/reference/operational-lessons.md`](docs/reference/operational-lessons.md).
