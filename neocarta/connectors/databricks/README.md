# Databricks Connector

Builds the neocarta semantic graph from Databricks Unity Catalog. The connector
extracts schema facts (databases, schemas, tables, columns), declared foreign
keys, and optional sampled column values, then writes them into Neo4j.

[neo4j-partners/dbxcarta](https://github.com/neo4j-partners/dbxcarta) provides a
Databricks job that runs the Spark ingestion, and the neocarta examples show how
to use it (see
[`examples/databricks/submit_finance_genie.env`](../../../examples/databricks/submit_finance_genie.env)).

## Quick start

Neocarta is one distribution. The base package gives you the library and CLI;
the Databricks Spark ingest is an optional extra on top of it. There are two
ways to get it, depending on whether you are running off-cluster or on a
Databricks cluster.

### Build a wheel from source (deploy to a cluster)

Building and staging this wheel is the step that updates a cluster so it can run
the neocarta Databricks Spark ingest. The schema ingest runs as a Spark wheel
job on a Databricks cluster, so the connector is delivered as a wheel staged on a
UC Volume. Build it from the repo root with `make`:

```bash
# In the neocarta repo root
make build
# produces dist/neocarta-<version>-py3-none-any.whl (and the sdist)
```

Optionally verify the built wheel before shipping it. `make databricks-wheel-test`
clean-room installs `neocarta[databricks-spark]` into a fresh venv and runs the
smoke suite against the wheel, catching modules or dependencies missing from the
package that the editable source tree hides:

```bash
make databricks-wheel-test
```

Copy the `.whl` from `dist/` to a UC Volume (workspace uploader,
`databricks fs cp`, or the Volumes UI) and point the notebook's `%pip install` at
it, then add the `[databricks-spark]` extra on the cluster:

```python
%pip install "/Volumes/<catalog>/<schema>/<volume>/neocarta-<version>-py3-none-any.whl[databricks-spark]"
```

The Neo4j Spark Connector JAR is a separate, JVM-level cluster library; attach
it once at the cluster level, not via pip. See
[`examples/databricks/inline_embed_ingest.py`](../../../examples/databricks/inline_embed_ingest.py)
for an end-to-end notebook.

### Install from PyPI (off-cluster / local development)

```bash
# Base neocarta library and CLI
pip install neocarta

# Add the Databricks Spark extra (pulls in pyspark) to run the connector
pip install "neocarta[databricks-spark]"
```

`databricks-sdk` ships in the base install, so the only thing the extra adds is
the heavy Spark dependency needed to actually run the ingest job.

### Set up the OpenAI external embedding endpoint

`scripts/setup_openai_external_model_endpoint.py` registers a Databricks Mosaic
AI External Model serving endpoint that proxies OpenAI `text-embedding-3-small`
(1536-dim). Run it so the Databricks connector embeds with the same OpenAI
embedding model as the rest of neocarta, keeping vector search consistent across
datasources in one graph. Key points:

- It makes inline embedding mode call OpenAI instead of a native Databricks
  model, matching an OpenAI-based neocarta graph.
- It is a standalone `uv` script with PEP 723 inline dependencies, so it runs
  without installing neocarta.

Store the OpenAI key in a Databricks secret scope first, then run the script:

```bash
databricks secrets create-scope neocarta-openai
databricks secrets put-secret neocarta-openai OPENAI_API_KEY

uv run scripts/setup_openai_external_model_endpoint.py --profile <profile>
```

The script creates the endpoint and probes it through `ai_query` to assert the
returned vector dimension. See
[Registering the OpenAI endpoint (manual step)](#registering-the-openai-endpoint-manual-step)
for the full flag list and details.

### Examples

[`examples/databricks/README.md`](../../../examples/databricks/README.md) covers
two runnable ways to drive the connector against Unity Catalog:

- **Local submit** (`submit_finance_genie.py`): a `uv` script that stages the
  connector wheel and submits the ingest job to a cluster.
- **Notebooks** (`inline_embed_ingest.py`, `graph_text2sql.py`): interactive
  ingest and queries inside a Databricks workspace.

### Run external embedding with the neocarta CLI

After the Spark ingest job builds the graph, embed the node descriptions with
OpenAI and write the vectors back using the neocarta CLI:

```bash
uv run neocarta databricks embed
# or override the model and dimensions:
uv run neocarta databricks embed --embedding-model text-embedding-3-small --embedding-dimensions 1536
```

The CLI loads a `.env` from the **current working directory** (not the Spark
job's env or any overlay) and reads these variables:

| Variable | Purpose | Default |
| --- | --- | --- |
| `NEO4J_URI` | Bolt URI of the graph to embed | required |
| `NEO4J_USERNAME` | Neo4j username | required |
| `NEO4J_PASSWORD` | Neo4j password | required |
| `NEO4J_DATABASE` | Target database | `neo4j` |
| `OPENAI_API_KEY` | OpenAI credential for the embedding model | required |
| `EMBEDDING_MODEL` | OpenAI embedding model | `text-embedding-3-small` |
| `EMBEDDING_DIMENSIONS` | Vector dimension to request | `768` |

> **Dimension must match the vector index.** The Spark ingest creates the
> `{label}_vector_index` indexes at `NEOCARTA_DATABRICKS_EMBEDDING_DIMENSION`
> (default `1024`; `1536` for the OpenAI endpoint). The CLI's `EMBEDDING_DIMENSIONS`
> default is `768`, which matches **neither** — embedding at the default writes
> 768-dim vectors that the index silently refuses to index, so vector search
> returns zero results. Set `EMBEDDING_DIMENSIONS` (or `--embedding-dimensions`)
> to the **same** value the index was built with.

`neocarta` is the console script installed with the package, so a bare
`neocarta …` invocation works once you have `pip install neocarta` into an
active environment. Developing from this repo with `uv`, the binary is not on
your `PATH`; prefix the command with `uv run` to run it inside the managed
environment:

```bash
uv run neocarta databricks embed
```

- Embeds Database, Schema, Table, and Column nodes, using a composed
  `name | type | description` text per node (null/blank parts dropped), so a
  node embeds on at least its name even without a comment.
- Requires `OPENAI_API_KEY`.
- `--dry-run` prints the planned run without touching Neo4j.
- `--json` produces machine-readable output.

See [Two-step external flow](#two-step-external-flow) for the full external mode
walkthrough.

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

## Node identity

Every node carries two identity fields with two distinct jobs:

- `id` — the Neo4j MERGE key. It is an md5 hash of the node's lowercased dotted
  path (`md5("catalog.schema.table.column")`), so it is a stable, opaque,
  collision-free key. It is never parsed apart; the structural parts are stored
  as their own properties (`catalog` / `schema` / `table`).
- `qualified_name` — the human-readable form of that path
  (`catalog.schema.table.column`), lowercased but otherwise verbatim. Kept for
  debugging and hand-written Cypher.

The id is hashed rather than stored as the dotted string to guarantee
collision-safety. Unity Catalog allows hyphens in names (e.g.
`graph-enriched-schema`), so a normalization that folded hyphens to underscores
would let two distinct schemas collapse to one id and silently corrupt the graph
on MERGE. Hashing the lossless lowercased path avoids this: because Unity Catalog
forbids `.` (and spaces and control characters) inside object names, the dotted
path is an unambiguous encoding of the identifier tuple, and its md5 is a
collision-free key. This differs from the in-process connectors (BigQuery, CSV,
Dataplex), which use the shared dotted-id scheme in
`neocarta.connectors.utils.generate_id`. See
`neocarta/connectors/databricks/ingest/contract_expr.py` for the full rationale.

## Keyword search indexes

neocarta retrieval is hybrid: it blends vector (embedding) similarity with
full-text (keyword) search and ranks the two together. The keyword half needs
Neo4j full-text indexes, and the index bootstrap creates them for every run,
independent of the embedding mode: `schema_full_text_index`,
`table_full_text_index`, and `column_full_text_index`, built via the shared
`neocarta.ingest.indexes.create_full_text_index` helper so the names match what
the MCP server's full-text Cypher queries by. This is the same set the other
connectors (BigQuery, CSV, Dataplex) create through the RDBMS loader. Database is
not full-text indexed, matching the other connectors.

Each index covers `name`, `qualified_name`, and `description`. Including
`qualified_name` (the dotted `catalog.schema.table` path) lets keyword search
disambiguate by catalog or schema: Lucene tokenizes the dotted path into separate
words, so the bare name still matches exactly while the catalog and schema words
become searchable too. This is a lexical-only choice — embeddings stay on the
bare `name | type | comment` text (see [Embedding modes](#embedding-modes)) to
keep every connector embedding identical text and avoid diluting vectors with
non-semantic catalog/schema words. The indexes are created with `IF NOT EXISTS`,
so reruns are safe.

## Embedding modes

Vectors can be produced in two ways. Both are fully supported, first-class
modes. External is the default behavior only because the inline flags default
to off.

Only inline mode creates the per-label `{label}_vector_index` cosine indexes
during the Spark job (at `NEOCARTA_DATABRICKS_EMBEDDING_DIMENSION`, one index per
label whose embedding flag is on), because only inline writes embeddings in the
job. External mode creates no vector indexes during ingest: the `neocarta
databricks embed` CLI creates each index at the dimension it actually embeds, so
the index dimension always matches the stored vectors. Value nodes are never
indexed.

### External mode (default)

The Spark job writes Database, Schema, Table, and Column nodes with no
`embedding` property and creates no vector indexes. A separate run of
`neocarta.enrichment` adds the vectors afterward and creates each vector index at
the dimension it embeds, so the index always matches the stored vectors. This is
a two-step flow, and neocarta ships a CLI verb for the second step. See
[Two-step external flow](#two-step-external-flow) below.

### Inline mode

* **How it runs**: during the node-write loop, each batch runs
  `ai_query('<endpoint>', embedding_text, failOnError => false)` natively in Spark
  against a Databricks model-serving endpoint.
* **Embedding text**: `embedding_text` is the composed `name | type | comment`
  string (null/blank parts dropped), the same text the external/shared embed path
  composes, so inline and external embed identically.
* **Per-label control**: each label can be enabled independently, and a per-label
  `{label}_vector_index` cosine index is created for each enabled label at the
  configured dimension.
* **Turning it on**: set one or more of the `include_embeddings_*` flags and an
  `NEOCARTA_DATABRICKS_EMBEDDING_STAGING_VOLUME`.
* **Value nodes**: never embedded in either mode. No neocarta retrieval path
  embeds Value nodes; they are reached by `HAS_VALUE` traversal, not vector search.

### Which mode to pick

Pick **inline** when the work already runs on a Databricks cluster and you want
one job to produce a fully embedded graph. It embeds in-cluster with `ai_query`
against a Databricks serving endpoint, uses Spark's distributed compute, and
needs no second process or external embedding provider.

Pick **external** when you want embeddings decoupled from ingest, want to use the
same `neocarta.enrichment` embedding path as the other connectors (for example
an OpenAI model), or want to re-embed without re-running the Spark job.

### Model and dimension consistency

Each mode owns its index. Inline creates the index during the Spark job at
`NEOCARTA_DATABRICKS_EMBEDDING_DIMENSION` (default: the Databricks
`databricks-gte-large-en` endpoint at 1024 dimensions). External creates no index
during ingest; the `neocarta databricks embed` CLI creates it at the dimension it
embeds (`EMBEDDING_DIMENSIONS`, default 768; set 1536 for OpenAI
`text-embedding-3-small`). The index is created with `IF NOT EXISTS` and is fixed
at one dimension, so two rules apply:

- In external mode, the CLI's `EMBEDDING_DIMENSIONS` must match the model it
  embeds with, and the query side (MCP server / agent) must use the same model
  and dimension or vector search returns nothing.
- You cannot mix modes against the same graph without rebuilding the vector
  index, and if the graph holds data from more than one neocarta datasource, the
  embedding model and dimension must match what the rest of neocarta uses or
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
descriptions with OpenAI and write the vectors back (prefix with `uv run` when
working from this repo):

```bash
neocarta databricks embed
# or override the model and dimensions:
neocarta databricks embed --embedding-model text-embedding-3-small --embedding-dimensions 768
```

The command embeds Database, Schema, Table, and Column nodes — each on a composed
`name | type | description` text (null/blank parts dropped) — and requires
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
