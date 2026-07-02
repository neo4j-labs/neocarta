# Environment Variables

Copy `.env.example` to `.env` and fill in the values before running any example scripts, the MCP server, or the agent.

```bash
cp .env.example .env
```

---

## Neo4j

| Variable | Required | Default | Description |
|---|---|---|---|
| `NEO4J_URI` | Yes | — | Bolt/HTTP URI for the Neo4j instance (e.g. `bolt://localhost:7687`) |
| `NEO4J_USERNAME` | Yes | — | Neo4j username |
| `NEO4J_PASSWORD` | Yes | — | Neo4j password |
| `NEO4J_DATABASE` | No | `neo4j` | Target database name |

Used by: all example scripts, MCP server, agent, workflows, integration tests.

---

## Embeddings & agent LLM (LiteLLM)

Embedding generation and the Text2SQL agent both route through [LiteLLM](https://docs.litellm.ai/), so any supported provider works by setting the matching model id and the provider's standard env vars.

| Variable | Required | Default | Description |
|---|---|---|---|
| `EMBEDDING_MODEL` | No | `text-embedding-3-small` | LiteLLM embedding model id (e.g. `text-embedding-3-small`, `gemini-embedding-001`) |
| `EMBEDDING_DIMENSIONS` | No | auto-detected | Vector dimension for models that support truncation (e.g. OpenAI `text-embedding-3-*`); silently ignored by models that don't. Defaults to the model's native dimension. |
| `EMBEDDING_BATCH_SIZE` | No | `100` | Nodes embedded per provider request during CLI ingest runs. Not used by the MCP server, which embeds one query at a time. |
| `AGENT_MODEL` | No | `gpt-4o-mini` | LiteLLM chat model id for the Text2SQL agent (e.g. `gpt-4o-mini`, `gemini-2.0-flash`) |

The embedding vector dimension is auto-detected from the model on first use and the Neo4j vector index is created at that size — no manual dimension config is required. Set `EMBEDDING_DIMENSIONS` only to request truncation on models that support it; models that don't support it ignore the value and keep their native dimension. `EMBEDDING_BATCH_SIZE` tunes throughput for CLI ingest runs and is not used by the MCP server. **If you switch to a model with a different dimension on an existing graph, drop the existing `*_vector_index` indexes first and re-ingest.**

For advanced setups (LiteLLM Proxy, custom self-hosted endpoints, or distinct keys for embeddings vs. completions), pass overrides programmatically via `LiteLLMEmbeddingsConnector(..., litellm_kwargs={"api_key": "...", "api_base": "..."})`. The standard provider env vars below cover all common cases.

### Provider credentials

Set whichever variables your chosen `EMBEDDING_MODEL` / `AGENT_MODEL` require:

| Provider | Variables |
|---|---|
| OpenAI | `OPENAI_API_KEY` |
| Gemini (AI Studio) | `GEMINI_API_KEY` |
| Cohere | `COHERE_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| Azure OpenAI | `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION` |
| AWS Bedrock | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION_NAME` |
| Vertex AI | `VERTEXAI_PROJECT`, `VERTEXAI_LOCATION` + ADC |

See the [LiteLLM provider docs](https://docs.litellm.ai/docs/providers) for the full list.

Used by: embeddings workflow, MCP server, agent, eval.

---

## Google Cloud Platform

| Variable | Required | Default | Description |
|---|---|---|---|
| `GCP_PROJECT_ID` | Yes (GCP workflows) | — | GCP project ID (string, e.g. `my-project`) |
| `GCP_PROJECT_NUMBER` | Yes (Dataplex) | — | Numeric GCP project number |

Used by: BigQuery schema connector, BigQuery logs connector, Dataplex connector, eval.

Authentication uses [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials). Run `gcloud auth application-default login` before using any GCP connector.

---

## BigQuery

| Variable | Required | Default | Description |
|---|---|---|---|
| `BIGQUERY_DATASET_ID` | Yes (BigQuery workflows) | — | Dataset ID to extract metadata from (e.g. `demo_ecommerce`) |
| `BIGQUERY_LOCATION` | No | — | BigQuery dataset location (e.g. `us`, `eu`) |
| `BIGQUERY_REGION` | No | `region-us` | Region string used when querying `INFORMATION_SCHEMA` job logs (e.g. `region-us`, `region-eu`) |

Used by: BigQuery schema connector, BigQuery logs connector, eval.

---

## Dataplex

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATAPLEX_LOCATION` | Yes (Dataplex workflows) | — | Location of the Dataplex glossary (e.g. `us`, `us-central1`) |
| `DATAPLEX_GLOSSARY_ID` | Yes (Dataplex workflows) | — | ID of the Dataplex Business Glossary to import terms from |

Used by: Dataplex connector, dataset setup scripts.

---

## Databricks

The connectors read no environment variables themselves — you build the
`databricks.sql` connection / `WorkspaceClient` from your own config. The
variables below are the conventional names used by the examples and `.env.example`.
Require the `databricks` extra (`pip install neocarta[databricks]`).

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABRICKS_SERVER_HOSTNAME` | Yes (schema connector) | — | SQL warehouse host, e.g. `dbc-xxxx.cloud.databricks.com` |
| `DATABRICKS_HTTP_PATH` | Yes (schema connector) | — | SQL warehouse HTTP path, e.g. `/sql/1.0/warehouses/abc123` |
| `DATABRICKS_CATALOG` | Yes (schema connector) | — | Unity Catalog catalog to ingest (the `:Database`) |
| `DATABRICKS_SCHEMA` | Yes (schema connector) | — | Schema to ingest (one per `ingest()` call) |
| `DATABRICKS_HOST` | Yes (governance-tags connector) | — | Workspace URL, e.g. `https://dbc-xxxx.cloud.databricks.com` |
| `DATABRICKS_TOKEN` | Yes | — | Personal access token (PAT), used by both connectors |

Used by: Databricks schema connector (SQL warehouse, `information_schema`) and the
Databricks governance-tags connector (Databricks SDK).

---

## Quick reference by component

| Component | Required variables |
|---|---|
| CSV connector | `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` |
| BigQuery schema connector | + `GCP_PROJECT_ID`, `BIGQUERY_DATASET_ID` |
| BigQuery logs connector | + `GCP_PROJECT_ID`, `BIGQUERY_DATASET_ID`, `BIGQUERY_REGION` |
| Dataplex connector | + `GCP_PROJECT_ID`, `GCP_PROJECT_NUMBER`, `DATAPLEX_LOCATION`, `DATAPLEX_GLOSSARY_ID` |
| Databricks schema connector | + `DATABRICKS_SERVER_HOSTNAME`, `DATABRICKS_HTTP_PATH`, `DATABRICKS_TOKEN`, `DATABRICKS_CATALOG`, `DATABRICKS_SCHEMA` |
| Embeddings workflow | + provider credentials for `EMBEDDING_MODEL` (e.g. `OPENAI_API_KEY`, `GEMINI_API_KEY`) |
| MCP server | `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, + provider credentials for `EMBEDDING_MODEL` |
| Agent (`run_agent.py`) | `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`, + provider credentials for `AGENT_MODEL` and `EMBEDDING_MODEL` |
| Eval | `GCP_PROJECT_ID`, `OPENAI_API_KEY` |