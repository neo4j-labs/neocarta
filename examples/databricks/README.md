# Databricks examples

Run the neocarta Databricks connector against Unity Catalog:

- **Notebooks** (`inline_embed_ingest.py`, `graph_text2sql.py`): run ingest and
  queries interactively inside a Databricks notebook, configured in-cell. Best
  for exploration and one-off runs in the workspace.

For setup (building the connector wheel, the OpenAI external embedding endpoint,
embedding modes, and the full `NEOCARTA_DATABRICKS_*` settings reference) see the
connector README,
[`neocarta/connectors/databricks/README.md`](../../neocarta/connectors/databricks/README.md).

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
