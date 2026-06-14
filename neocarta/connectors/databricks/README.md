# Databricks Connector

Builds the neocarta semantic graph from Databricks Unity Catalog. The connector
extracts schema facts (databases, schemas, tables, columns), declared foreign
keys, and optional sampled column values, then writes them into Neo4j.

## Execution model

Unlike the in-process connectors (BigQuery, CSV, Dataplex), the schema ingest
runs as a **Spark job** and writes to Neo4j through the Neo4j Spark Connector. It
does not use `Neo4jRDBMSLoader`. It needs a Spark session: a local session, a
Spark Connect session, or a Databricks cluster. On a cluster the Neo4j
credentials are read from the Databricks secret scope.

The Spark dependencies are an optional extra:

```bash
pip install neocarta[databricks-spark]
```

Configuration is read from `NEOCARTA_DATABRICKS_*` environment variables.
Databricks auth and connection (host, token, profile, cluster id) use the
Databricks SDK's own `DATABRICKS_*` variables and are not redefined here.

## Embedding modes

Vectors can be produced in two ways. Both are fully supported, first-class
modes. External is the default behavior only because the inline flags default
to off.

### External mode (default)

The Spark job writes Database, Schema, Table, and Column nodes with no
`embedding` property and creates no vector indexes. A separate run of
`neocarta.enrichment` adds the vectors afterward. This is a two-step flow, and
neocarta ships a CLI verb for the second step. See
[Two-step external flow](#two-step-external-flow) below.

### Inline mode

During the node-write loop, each batch runs
`ai_query('<endpoint>', embedding_text, failOnError => false)` natively in
Spark against a Databricks model-serving endpoint. There are no Python UDFs and
no driver-side collection of table data. Each label can be enabled
independently, and a per-label `{label}_vector_index` cosine index is created
for each enabled label at the configured dimension. Turn inline on by setting
one or more of the `include_embeddings_*` flags and an
`NEOCARTA_DATABRICKS_EMBEDDING_STAGING_VOLUME`.

Value nodes are never embedded in either mode. No neocarta retrieval path embeds
Value nodes; they are reached by `HAS_VALUE` traversal, not vector search.

### Which mode to pick

Pick **inline** when the work already runs on a Databricks cluster and you want
one job to produce a fully embedded graph. It embeds in-cluster with `ai_query`
against a Databricks serving endpoint, uses Spark's distributed compute, and
needs no second process or external embedding provider.

Pick **external** when you want embeddings decoupled from ingest, want to use the
same `neocarta.enrichment` embedding path as the other connectors (for example
an OpenAI model), or want to re-embed without re-running the Spark job.

### Model and dimension consistency

Each mode owns its own vector-index configuration. Inline mode defaults to the
Databricks `databricks-gte-large-en` endpoint at 1024 dimensions. External mode
uses whatever `neocarta.enrichment` is pointed at, for example OpenAI
`text-embedding-3-small`. These produce different vectors at different
dimensions, so two rules apply:

- You cannot mix modes against the same graph without rebuilding the vector
  index. The index is created at one fixed dimension.
- If the graph holds data from more than one neocarta datasource, the inline
  embedding model and dimension must match what the rest of neocarta uses, or
  vector search across sources is inconsistent. The inline path logs a warning
  at startup so the operator notices this.

To make inline match an OpenAI-based neocarta graph, register a Databricks
Mosaic AI External Models endpoint that proxies OpenAI `text-embedding-3-small`
(1536 dimensions) and point `NEOCARTA_DATABRICKS_EMBEDDING_ENDPOINT` at it. Set
`NEOCARTA_DATABRICKS_EMBEDDING_DIMENSION` to match the chosen endpoint.

### Registering the OpenAI endpoint (manual step)

Inline mode embeds by calling `ai_query('<endpoint>', ...)` against a Databricks
serving endpoint. To run that on OpenAI rather than a native Databricks model,
register an "External Model" serving endpoint. "External Model" is the Databricks
Mosaic AI term for a serving endpoint that proxies an outside provider; the one
here proxies OpenAI `text-embedding-3-small` (1536-dim) and is then callable with
`ai_query` exactly like a native endpoint. This is a one-time manual step done
outside the connector run, and the repo ships a helper,
`scripts/setup_openai_external_model_endpoint.py`, that automates it. The helper
is a standalone `uv` script (PEP 723 inline dependencies), so it runs without
installing neocarta.

1. Store the OpenAI key in a Databricks secret scope. The endpoint references the
   secret and authenticates to OpenAI itself at query time, so the key value
   never leaves Databricks and never appears in the connector run or the ingest
   notebook:

   ```bash
   databricks secrets create-scope neocarta-openai
   databricks secrets put-secret neocarta-openai OPENAI_API_KEY
   ```

2. Create and verify the endpoint. The script creates the External Model serving
   endpoint that proxies OpenAI `text-embedding-3-small` (1536-dim), then probes
   it through the same `ai_query` path the connector uses to assert the returned
   vector dimension:

   ```bash
   uv run scripts/setup_openai_external_model_endpoint.py --profile <profile>
   ```

   Pass `--skip-verify` to create the endpoint without the dimension probe, or
   `--endpoint-name` / `--secret-scope` / `--secret-key` to override the
   defaults. Run with `--help` for the full flag list.

3. Point the connector at the endpoint:

   ```bash
   export NEOCARTA_DATABRICKS_EMBEDDING_ENDPOINT=openai-text-embedding-3-small
   export NEOCARTA_DATABRICKS_EMBEDDING_DIMENSION=1536
   ```

## Two-step external flow

External mode is two steps: run the Spark ingest job, then run the CLI embedding
command against the graph it produced.

**Step 1: Spark ingest job (on a Databricks cluster).** Configure the
`NEOCARTA_DATABRICKS_*` variables and run the connector as a wheel job. The
schema ingest cannot run in-process off-cluster because it writes through the
Neo4j Spark Connector.

```python
from neocarta.connectors.databricks import DatabricksSparkSchemaConnector

# On a cluster: Neo4j credentials come from the Databricks secret scope.
summary = DatabricksSparkSchemaConnector().run()
```

**Step 2: CLI embedding command.** After the graph exists, embed the
descriptions with OpenAI and write the vectors back:

```bash
neocarta databricks embed
# or override the model and dimensions:
neocarta databricks embed --embedding-model text-embedding-3-small --embedding-dimensions 768
```

The command embeds Database, Schema, Table, and Column descriptions and requires
`OPENAI_API_KEY`. Pass `--dry-run` to print the planned run without touching
Neo4j, and `--json` for machine-readable output. The Spark ingest itself is not a
CLI verb, and inline embeddings remain a setting on the Spark job rather than a
CLI flag.

## Capturing the run report

Every run produces a `RunSummary` with extract, sample-value, foreign-key, and
embedding counters. The `run()` call returns it in memory, and the Neo4j write
counts are logged. A detached cluster job leaves no durable artifact beyond those
logs, so set `NEOCARTA_DATABRICKS_SUMMARY_VOLUME` to a writable UC Volume subpath
to persist the report:

```bash
export NEOCARTA_DATABRICKS_SUMMARY_VOLUME=/Volumes/<catalog>/<schema>/<volume>/runs
```

Each run then writes `summary_<run_id>.json` (the flattened `RunSummary`) beneath
that path. Persistence is mode-independent, runs in both external and inline mode,
and is durable. It is best-effort: a write failure is logged, never raised, so it
cannot mask the run outcome. Blank (the default) disables it.

## Cross-run embedding ledger (inline only)

A cross-run cache lets inline mode skip the `ai_query` call for nodes that have
not changed since the last run. Each embedded node stores the SHA-256 hash of the
exact text that was embedded. The ledger keeps a small Delta table per label
holding the id, that text hash, the resulting vector, the model name, and a
timestamp. On the next run, a node is a hit when its id, model, and text hash all
match, and the stored vector is reused with no embedding call. Only misses go to
`ai_query`, and successful batches are merged back into the ledger.

The point is cost and speed: most metadata does not change between runs, so the
ledger turns a full re-embed into embedding only the rows whose text actually
changed. Enable it with `NEOCARTA_DATABRICKS_LEDGER_ENABLED=true`. It is off by
default. A blank `NEOCARTA_DATABRICKS_LEDGER_PATH` derives a sibling `ledger`
directory under the same UC volume as the staging volume.

## Settings reference

All variables use the `NEOCARTA_DATABRICKS_` prefix.

### Core ingest

| Variable | Default | Meaning |
|---|---|---|
| `CATALOG` | (required) | Primary Unity Catalog to ingest. |
| `CATALOGS` | `""` | Comma-separated `catalog` or `catalog:layer` entries to ingest into one graph. Blank means just `CATALOG`. |
| `SCHEMAS` | `""` | Comma-separated schema names. Blank means every schema in the catalog. |
| `PLATFORM` | `""` | Cloud tag for the Database `platform` property (AWS/AZURE/GCP). Blank yields null. |
| `SECRET_SCOPE` | `""` | Databricks secret scope holding the Neo4j credentials read on-cluster. |
| `INCLUDE_VALUES` | `true` | Sample distinct column values and write Value nodes. |
| `SAMPLE_LIMIT` | `10` | Max sampled values per column. |
| `SAMPLE_CARDINALITY_THRESHOLD` | `50` | Columns with distinct counts below this are sampled. |
| `NEO4J_BATCH_SIZE` | `20000` | Neo4j Spark Connector `batch.size`. |
| `REL_WRITE_PARTITIONS` | `1` | Relationship write parallelism. 1 coalesces to a single partition. |
| `FK_MAX_COLUMNS` | `0` | Skip declared-FK discovery above this column count. 0 disables the guardrail. |
| `SUMMARY_VOLUME` | `""` | UC Volume subpath for `summary_<run_id>.json`. Blank disables persistence. |

### Inline embeddings

| Variable | Default | Meaning |
|---|---|---|
| `INCLUDE_EMBEDDINGS_TABLES` | `false` | Embed Table nodes inline. |
| `INCLUDE_EMBEDDINGS_COLUMNS` | `false` | Embed Column nodes inline. |
| `INCLUDE_EMBEDDINGS_SCHEMAS` | `false` | Embed Schema nodes inline. |
| `INCLUDE_EMBEDDINGS_DATABASES` | `false` | Embed Database nodes inline. |
| `EMBEDDING_ENDPOINT` | `databricks-gte-large-en` | Databricks model-serving endpoint used by `ai_query`. |
| `EMBEDDING_DIMENSION` | `1024` | Expected vector length, checked against the endpoint at preflight. |
| `EMBEDDING_BATCH_TABLES` | `200` | Tables per embed-and-write batch. Must be >= 1. |
| `EMBEDDING_FAILURE_MAX` | `0` | Per-batch failure-count gate. If a batch produces more than this many embedding errors, the run fails before the batch is written. 0 disables the gate. |
| `EMBEDDING_STAGING_VOLUME` | `""` | Writable UC Volume subpath for the transient per-batch `ai_query` materialization. Required when any inline flag is on. |
| `LEDGER_ENABLED` | `false` | Enable the cross-run embedding ledger. |
| `LEDGER_PATH` | `""` | Durable Delta ledger root. Blank derives a sibling of the staging volume. |
