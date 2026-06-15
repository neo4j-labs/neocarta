# Databricks examples

Two ways to run the neocarta Databricks connector against Unity Catalog:

- **Local submit** (`submit_finance_genie.py`): run a `uv` script from your
  machine. It uses [`dbxcarta-submit`](https://pypi.org/project/dbxcarta-submit/)
  from [dbxcarta](https://github.com/neo4j-partners/dbxcarta) to stage the
  connector wheel and submit the ingest job to a cluster. Best for operators
  driving a deployment from a terminal.
- **Notebooks** (`inline_embed_ingest.py`, `graph_text2sql.py`): run ingest and
  queries interactively inside a Databricks notebook, configured in-cell. Best
  for exploration and one-off runs in the workspace.

For setup (building the connector wheel, the OpenAI external embedding endpoint,
embedding modes, and the full `NEOCARTA_DATABRICKS_*` settings reference) see the
connector README,
[`neocarta/connectors/databricks/README.md`](../../neocarta/connectors/databricks/README.md).

## Submit the finance-genie ingest job (`submit_finance_genie.py`)

A single `uv` script that uses
[`dbxcarta-submit`](https://pypi.org/project/dbxcarta-submit/) from
[dbxcarta](https://github.com/neo4j-partners/dbxcarta) to stage a prebuilt
neocarta connector wheel on a UC Volume and submit the ingest job. The
job runs on a cluster and writes the finance-genie semantic graph into Neo4j. No
dbxcarta checkout is needed.

Embeddings can be generated inline as part of this ingest job, or externally
afterward with neocarta. Both are neocarta features; see the connector README
([Embedding modes](../../neocarta/connectors/databricks/README.md#embedding-modes))
for details.

### Prerequisites

- A **classic (non-serverless) cluster** with the **Neo4j Spark Connector**
  attached as a JVM library. Ingest writes through that connector, which is not
  supported on serverless compute.
- A reachable **Neo4j** instance, and a **Databricks secret scope** holding its
  credentials, already provisioned. The scope name is
  `NEOCARTA_DATABRICKS_SECRET_SCOPE` in the config. The cluster reads Neo4j
  credentials from it; they are never in this repo.
- **Databricks auth** for the profile named in the config (a
  `~/.databrickscfg` profile, or the SDK auth chain).
- A built neocarta wheel. Build it with `make build`; it produces
  `dist/neocarta-<version>-py3-none-any.whl`.

### Set the secrets

The job runs on the cluster and reads the Neo4j credentials at runtime from the
Databricks secret scope named in `NEOCARTA_DATABRICKS_SECRET_SCOPE`
(`dbxcarta-neo4j-finance-genie` in the sample config). They never live in this
repo or in `submit_finance_genie.env`. Create the scope and put the three keys
the cluster reads, `NEO4J_URI`, `NEO4J_USERNAME`, and `NEO4J_PASSWORD`:

```bash
databricks secrets create-scope dbxcarta-neo4j-finance-genie
databricks secrets put-secret dbxcarta-neo4j-finance-genie NEO4J_URI
databricks secrets put-secret dbxcarta-neo4j-finance-genie NEO4J_USERNAME
databricks secrets put-secret dbxcarta-neo4j-finance-genie NEO4J_PASSWORD
```

Each `put-secret` opens an editor for the value, so the credential is never on
the command line. Use the same scope name you set for
`NEOCARTA_DATABRICKS_SECRET_SCOPE`.

If you run inline embeddings, the OpenAI External Model endpoint reads the OpenAI
key from its own secret scope. That secret is set when you register the endpoint;
see the connector README
([Registering the OpenAI endpoint](../../neocarta/connectors/databricks/README.md)).

### Run it

1. Build the connector wheel per the connector README above, so a
   `dist/neocarta-*.whl` exists.

2. Copy the config and fill in the infra values:

   ```bash
   cp examples/databricks/submit_finance_genie.env.sample \
      examples/databricks/submit_finance_genie.env
   # edit DATABRICKS_PROFILE, DATABRICKS_CLUSTER_ID, DATABRICKS_WAREHOUSE_ID, etc.
   ```

   The populated `submit_finance_genie.env` is local-only and gitignored. It is
   secret-free: it carries no Neo4j credentials.

3. Submit:

   ```bash
   uv run examples/databricks/submit_finance_genie.py
   ```

   `uv` installs `dbxcarta-submit` into a throwaway environment, then the script
   stages the prebuilt connector wheel and submits the ingest job. By default it
   uses the newest `dist/neocarta-*.whl`; pass a wheel path as the first argument
   to override.

4. (Optional) If inline embeddings were not enabled on the ingest job, generate
   them afterward with neocarta:

   ```bash
   uv run neocarta databricks embed
   ```

   See the connector README
   ([`neocarta/connectors/databricks/README.md`](../../neocarta/connectors/databricks/README.md))
   for details.

## Notebooks

- `inline_embed_ingest.py` — ingest plus inline embeddings in one cluster job,
  configured by constructing the settings directly in the notebook.
- `graph_text2sql.py` — query the resulting graph.

Embeddings can be generated inline as part of the ingest notebook, or externally
afterward with neocarta. Both are neocarta features; see the connector README
([Embedding modes](../../neocarta/connectors/databricks/README.md#embedding-modes))
for details.

## Compare retrieval strategies locally (`compare_retrievers.py`)

A `uv` script that runs one query through every retrieval strategy the neocarta
MCP server exposes and prints the ranked tables each returns, plus a comparison
matrix. It covers vector, full-text, hybrid, and business-term hybrid search at
both the table and column level. Use it to sanity-check a graph after ingest and
to see how the strategies differ on the same question.

The script reuses the exact Cypher the MCP server runs (`neocarta._mcp.cypher`)
and the same embedder (`LiteLLMEmbeddingsConnector`), so it is a faithful local
test of production retrieval. It runs against the Neo4j instance in your `.env`
and is read-only: it only performs vector and full-text index lookups.

### Prerequisites

- A populated neocarta graph in the Neo4j instance named in `.env`.
- The search indexes the strategies query. Vector indexes are created during
  ingest. The full-text indexes (`schema_full_text_index`, `table_full_text_index`,
  `column_full_text_index`) are created by the ingest pipeline's bootstrap step,
  so a graph ingested before that step existed needs a rerun. Strategies whose
  index is missing are skipped with a printed reason rather than failing the run.
- An `EMBEDDING_MODEL` that matches the model and dimension used at ingest, for
  the vector and hybrid strategies to be meaningful. A Databricks graph embedded
  via `ai_query('openai-text-embedding-3-small', ...)` lines up with the LiteLLM
  model `text-embedding-3-small`. Full-text search uses no embeddings and is
  unaffected by this.

### Environment variables

Read from `.env` (or the process environment):

- `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`
- `NEO4J_DATABASE` (optional, defaults to `neo4j`)
- `EMBEDDING_MODEL` (optional, defaults to `text-embedding-3-small`)
- Provider credentials for that model, for example `OPENAI_API_KEY`

### Run it

Run every strategy for one question:

```bash
uv run examples/databricks/compare_retrievers.py \
  --query "Which account types have the most fraud-labeled accounts?"
```

Run a subset of strategies with wider recall and more rows printed:

```bash
uv run examples/databricks/compare_retrievers.py \
  --query "fraud labeled accounts" \
  --strategies tbl-vec tbl-ft tbl-hyb \
  --search-top-k 20 --max-tables 10 --top 10
```

Options:

- `--strategies` selects which strategies to run. Defaults to all. Choices are
  `tbl-vec`, `tbl-ft`, `tbl-hyb`, `tbl-bt`, `sch-tbl-vec`, `col-vec`, `col-ft`,
  `col-hyb`, `col-bt`.
- `--search-top-k` sets how many candidates each search branch returns before
  ranking (default 10).
- `--max-tables` caps the tables kept per strategy (default 5).
- `--top` sets how many ranked rows to print per strategy and in the comparison
  matrix (default 5).
