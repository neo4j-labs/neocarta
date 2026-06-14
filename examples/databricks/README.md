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
- A built neocarta wheel. Build it first following
  [`neocarta/connectors/databricks/README.md`](../../neocarta/connectors/databricks/README.md)
  ("Build a wheel from source"); it produces `dist/neocarta-<version>-py3-none-any.whl`.

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

## Notebooks

- `inline_embed_ingest.py` — ingest plus inline embeddings in one cluster job,
  configured by constructing the settings directly in the notebook.
- `graph_text2sql.py` — query the resulting graph.

Embeddings can be generated inline as part of the ingest notebook, or externally
afterward with neocarta. Both are neocarta features; see the connector README
([Embedding modes](../../neocarta/connectors/databricks/README.md#embedding-modes))
for details.
