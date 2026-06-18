# Databricks Connector

Builds the neocarta semantic graph from Databricks Unity Catalog. The connector
extracts schema facts (databases, schemas, tables, columns), declared foreign
keys, and optional sampled column values, then writes them into Neo4j.

This connector's Spark ingestion code originated in
[neo4j-partners/dbxcarta](https://github.com/neo4j-partners/dbxcarta), the
original source for this Databricks semantic-layer work. Beyond the ingestion
logic ported here, dbxcarta additionally provides job-submission tooling,
`dbxcarta-submit`, for packaging the neocarta wheel and launching the ingest as a
Spark wheel job on a cluster. neocarta itself does not ship that tooling.

## Quick start

Neocarta is one distribution. The base package gives you the library and CLI;
the Databricks Spark ingest is an optional extra on top of it. There are two
ways to get it, depending on whether you are running off-cluster or on a
Databricks cluster.

### Build a wheel from source (deploy to a cluster)

Building and staging this wheel is the step that updates a cluster so it can run
the neocarta Databricks Spark ingest. The schema ingest runs as a Spark wheel
job on a Databricks cluster, so the connector is delivered as a wheel staged on a
UC Volume. Build it from the repo root with `uv`:

```bash
# In the neocarta repo root
uv build
# produces dist/neocarta-<version>-py3-none-any.whl (and the sdist)
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

### Examples

[`examples/databricks/README.md`](../../../examples/databricks/README.md) covers
runnable ways to drive the connector against Unity Catalog:

- **Notebooks** (`inline_embed_ingest.py`, `graph_text2sql.py`): interactive
  ingest and queries inside a Databricks workspace.

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

- `id`: the Neo4j MERGE key. It is the shared neocarta `compose_id` of the node's
  parts: each part lowercased with spaces and hyphens folded to underscore, joined
  with `.` (`catalog.schema.table.column`). It is never parsed apart; the
  structural parts are stored as their own properties `catalog` / `schema` /
  `table`.
- `qualified_name`: the human-readable, lossless form of that path
  (`catalog.schema.table.column`), lowercased but otherwise verbatim, so hyphens
  are preserved. Kept for debugging and hand-written Cypher.

The `id` uses the same scheme as the in-process connectors (BigQuery, CSV,
Dataplex) in `neocarta.connectors.utils.generate_id`, so node ids are uniform
across connectors. The normalization is lossy: a schema named
`graph-enriched-schema` and one named `graph_enriched_schema` fold to the same
`id` and MERGE collapses them into one node. `qualified_name` keeps the distinct
readable paths even where the id folds them. See
`neocarta/connectors/databricks/ingest/contract_expr.py` for details.

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
become searchable too. This is a lexical-only choice. Embeddings stay on the
`description` text only (see [Embedding modes](#embedding-modes)) to keep every
connector embedding identical text and avoid diluting vectors with non-semantic
catalog/schema words. The indexes are created with `IF NOT EXISTS`, so reruns are
safe.

## Embedding modes

Vectors can be produced in two ways. Both are fully supported, first-class
modes. External is the default behavior only because the inline flags default
to off.

Only inline mode creates the per-label `{label}_vector_index` cosine indexes
during the Spark job (at `NEOCARTA_DATABRICKS_EMBEDDING_DIMENSION`, one index per
label whose embedding flag is on), because only inline writes embeddings in the
job. External mode creates no vector indexes during ingest; the separate
external embedding step creates each index at the dimension it actually embeds,
so the index dimension always matches the stored vectors. Value nodes are never
indexed.

### External mode (default)

The Spark job writes Database, Schema, Table, and Column nodes with no
`embedding` property and creates no vector indexes. Embedding is a separate step
performed against the graph after ingest: it adds the vectors and creates each
vector index at the dimension it embeds, so the index always matches the stored
vectors.

### Inline mode

* **How it runs**: during the node-write loop, each batch runs
  `ai_query('<endpoint>', embedding_text, failOnError => false)` natively in Spark
  against a Databricks model-serving endpoint.
* **Embedding text**: `embedding_text` is the node's `description` only, the same
  text the external/shared embed path uses, so inline and external embed
  identically. A node with no description is written without an embedding (and is
  not vector-indexed), mirroring neocarta's description-only embedding.
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
during ingest; the separate external embedding step creates it at the dimension
it embeds. The index is created with `IF NOT EXISTS` and is fixed at one
dimension, so two rules apply:

- In external mode, the embedding step's dimension must match the model it embeds
  with, and the query side (MCP server / agent) must use the same model and
  dimension or vector search returns nothing.
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
outside the connector run.

1. Store the OpenAI key in a Databricks secret scope. The endpoint references the
   secret and authenticates to OpenAI itself at query time, so the key value
   never leaves Databricks and never appears in the connector run or the ingest
   notebook:

   ```bash
   databricks secrets create-scope neocarta-openai
   databricks secrets put-secret neocarta-openai OPENAI_API_KEY
   ```

2. Create the External Model serving endpoint that proxies OpenAI
   `text-embedding-3-small` (1536-dim), referencing the secret above for the
   OpenAI credential. Create it through the Databricks Serving UI or the
   Databricks REST API / SDK.

3. Point the connector at the endpoint:

   ```bash
   export NEOCARTA_DATABRICKS_EMBEDDING_ENDPOINT=openai-text-embedding-3-small
   export NEOCARTA_DATABRICKS_EMBEDDING_DIMENSION=1536
   ```

## Running the Spark ingest

Configure the `NEOCARTA_DATABRICKS_*` variables and run the connector as a wheel
job on a Databricks cluster. The schema ingest cannot run in-process off-cluster
because it writes through the Neo4j Spark Connector.

```python
from neocarta.connectors.databricks import DatabricksSparkSchemaConnector

# On a cluster: Neo4j credentials come from the Databricks secret scope.
summary = DatabricksSparkSchemaConnector().ingest()
```

In external mode the job stops here, having written the schema graph; embedding
is a separate step performed against that graph afterward.

## Capturing the run report

Every run produces a `RunSummary` with extract, sample-value, foreign-key, and
embedding counters. The `ingest()` call returns it in memory, and the Neo4j write
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
