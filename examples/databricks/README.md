# Databricks examples

Run the neocarta Databricks connector against Unity Catalog from inside a
Databricks workspace. Two notebooks drive the workflow:

- `inline_embed_ingest.py` — ingest Unity Catalog schema into Neo4j, optionally
  generating vector embeddings inline in the same Spark job. Configured in-cell.
- `graph_text2sql.py` — query the resulting graph interactively.

These are Databricks source notebooks: import them into your workspace, fill in
the values at the top, and run each top to bottom. For setup that lives outside
the notebooks (building the connector wheel, registering the OpenAI external
embedding endpoint, embedding modes, and the full `NEOCARTA_DATABRICKS_*`
settings reference) see the connector README,
[`neocarta/connectors/databricks/README.md`](../../neocarta/connectors/databricks/README.md).

## Steps

### 1. Set up the sample dataset

The connector ingests an existing Unity Catalog, so you need a catalog to point
it at. If you do not already have one, stage the sample finance dataset:

1. Open the
   [`00_setup_data.ipynb`](https://github.com/neo4j-partners/graph-on-databricks/blob/main/finance-genie/workshop/00_setup_data.ipynb)
   notebook from the `graph-on-databricks` repo in your Databricks workspace.
2. Run it top to bottom. It creates the `graph-on-databricks` catalog and
   `graph-enriched-schema` schema, populated with five fraud-detection tables:
   `accounts`, `merchants`, `transactions`, `account_links`, and
   `account_labels`, complete with column comments and foreign-key constraints.

Skip this step if you are pointing the connector at your own catalog.

### 2. Ingest the schema into Neo4j

1. Import `inline_embed_ingest.py` into your Databricks workspace and attach it
   to a classic cluster (the Spark ingest writes through the Neo4j Spark
   Connector, a JVM library that is unsupported on serverless).
2. Set `NEOCARTA_DATABRICKS_CATALOG` to the catalog from step 1 (for example
   `graph-on-databricks`) and fill in the remaining values at the top of the
   notebook.
3. Run the notebook top to bottom to write the schema graph into Neo4j.

Embeddings can be generated inline as part of this notebook, or externally
afterward with neocarta. Both are neocarta features; see the connector README
([Embedding modes](../../neocarta/connectors/databricks/README.md#embedding-modes))
for which mode to pick and how to configure it.

### 3. Query the graph

1. Import `graph_text2sql.py` into the same workspace.
2. Run it to query the graph produced in step 2.
