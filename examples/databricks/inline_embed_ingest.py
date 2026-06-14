# Databricks notebook source
# MAGIC %md
# MAGIC # Databricks Connector: Ingest + Inline Embeddings
# MAGIC
# MAGIC This notebook ingests Unity Catalog schema (databases, schemas, tables,
# MAGIC columns, and sampled values) into Neo4j and generates vector embeddings
# MAGIC **inline**, in the same Spark job, using `ai_query` against a Databricks
# MAGIC model-serving endpoint. One run produces a fully embedded semantic graph.
# MAGIC
# MAGIC This is the **inline mode** described in the connector README. It runs on
# MAGIC the cluster; there is no separate enrichment step. (The alternative is
# MAGIC external mode: ingest first, then run `neocarta databricks embed` to add
# MAGIC vectors. See the connector README for that two-step flow.)
# MAGIC
# MAGIC **Requires a classic cluster.** The Neo4j Spark Connector is a JVM library
# MAGIC and is not supported on serverless compute.
# MAGIC
# MAGIC See `neocarta/connectors/databricks/README.md` for the full settings reference.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Prerequisites
# MAGIC
# MAGIC Before running this notebook, make sure all of the following are in place:
# MAGIC
# MAGIC - A **classic (non-serverless) cluster**.
# MAGIC - The **Neo4j Spark Connector** JAR attached to the cluster as a library
# MAGIC   (a JVM library, attached once at the cluster level, not pip-installed).
# MAGIC - A reachable **Neo4j** instance (URI, username, password).
# MAGIC - A Databricks **model-serving endpoint** for embeddings. The default is
# MAGIC   `databricks-gte-large-en` (1024 dimensions).
# MAGIC - The neocarta **connector wheel staged on a UC Volume** (see below).
# MAGIC - A writable **UC Volume** path for the transient per-batch embedding
# MAGIC   staging (`EMBEDDING_STAGING_VOLUME`).
# MAGIC
# MAGIC ### Staging the wheel for local testing
# MAGIC
# MAGIC Until the wheel is published to an index, build it locally and copy it to
# MAGIC a Volume:
# MAGIC
# MAGIC 1. In the neocarta repo: `uv build` (produces
# MAGIC    `dist/neocarta-<version>-py3-none-any.whl`).
# MAGIC 2. Copy that one `.whl` file to a UC Volume path (workspace file uploader,
# MAGIC    `databricks fs cp`, or the Volumes UI).
# MAGIC 3. Edit the `%pip install` line in the next cell to point at it.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Install the connector wheel
# MAGIC
# MAGIC Installs the staged wheel with the `databricks-spark` extra (pulls pyspark
# MAGIC and the connector runtime deps), then restarts Python so the install takes
# MAGIC effect. Edit the path to your staged wheel. The restart clears notebook
# MAGIC variables, so all configuration is set *after* it, below.

# COMMAND ----------

# MAGIC %pip install /Volumes/<catalog>/<schema>/<volume>/wheels/neocarta-0.6.0-py3-none-any.whl[databricks-spark]

# COMMAND ----------

dbutils.library.restartPython()  # noqa: F821 — provided by the Databricks runtime

# COMMAND ----------

# MAGIC %md
# MAGIC ## Fill these in
# MAGIC
# MAGIC Everything the run needs is in this cell. (It is below the restart so the
# MAGIC values survive.)

# COMMAND ----------

# Unity Catalog to ingest.
CATALOG = "<catalog>"
# Comma-separated schema names. Leave blank for every schema in the catalog.
SCHEMAS = ""

# Neo4j connection.
NEO4J_URI = "neo4j+s://<host>:7687"
NEO4J_USERNAME = "neo4j"
NEO4J_PASSWORD = "<password>"

# Inline embedding configuration.
EMBEDDING_ENDPOINT = "databricks-gte-large-en"
EMBEDDING_DIMENSION = "1024"
# Writable UC Volume subpath for the transient per-batch ai_query materialization.
EMBEDDING_STAGING_VOLUME = "/Volumes/<catalog>/<schema>/<volume>/embed_staging"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Neo4j Spark Connector
# MAGIC
# MAGIC The connector writes to Neo4j through the **Neo4j Spark Connector**, a JVM
# MAGIC library. It is *not* a pip dependency, so this notebook does not install it.
# MAGIC Attach it to the cluster once as a Maven/JAR library (a one-time cluster
# MAGIC setting). If it is missing, the write step below will fail.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configure the run (environment variables)
# MAGIC
# MAGIC The connector reads its configuration from `NEOCARTA_DATABRICKS_*`
# MAGIC environment variables. Setting the `INCLUDE_EMBEDDINGS_*` flags here is what
# MAGIC turns on **inline mode**. Leaving them off (the default) would produce an
# MAGIC un-embedded graph (external mode) instead.

# COMMAND ----------

import os

os.environ["NEOCARTA_DATABRICKS_CATALOG"] = CATALOG
os.environ["NEOCARTA_DATABRICKS_SCHEMAS"] = SCHEMAS

# Turn on inline embeddings for Table and Column nodes (the labels neocarta
# retrieval embeds). Value nodes are never embedded in either mode.
os.environ["NEOCARTA_DATABRICKS_INCLUDE_EMBEDDINGS_TABLES"] = "true"
os.environ["NEOCARTA_DATABRICKS_INCLUDE_EMBEDDINGS_COLUMNS"] = "true"

os.environ["NEOCARTA_DATABRICKS_EMBEDDING_ENDPOINT"] = EMBEDDING_ENDPOINT
os.environ["NEOCARTA_DATABRICKS_EMBEDDING_DIMENSION"] = EMBEDDING_DIMENSION
os.environ["NEOCARTA_DATABRICKS_EMBEDDING_STAGING_VOLUME"] = EMBEDDING_STAGING_VOLUME

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run the ingest
# MAGIC
# MAGIC Builds settings from the environment variables above, passes the Neo4j
# MAGIC connection explicitly, and runs the full ingest. The inline embedding step
# MAGIC happens inside the node-write loop. Returns a `RunSummary`.

# COMMAND ----------

from neocarta.connectors.databricks.ingest.load.neo4j_io import Neo4jConfig
from neocarta.connectors.databricks.run import run_ingest

neo4j = Neo4jConfig(uri=NEO4J_URI, username=NEO4J_USERNAME, password=NEO4J_PASSWORD)

summary = run_ingest(neo4j=neo4j)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Results
# MAGIC
# MAGIC The run summary reports node/row counts and the inline embedding counters
# MAGIC (attempts and successes per label). Non-zero `embedding_successes` for
# MAGIC Table and Column confirms the graph was embedded in this one job.

# COMMAND ----------

import json

print(json.dumps(summary.to_dict(), indent=2))

# COMMAND ----------

# MAGIC %md
# MAGIC ## What next
# MAGIC
# MAGIC - In Neo4j, the inline run created per-label cosine vector indexes named
# MAGIC   `{Label}_vector_index` (for example `Table_vector_index`,
# MAGIC   `Column_vector_index`) at the configured dimension. These are the indexes
# MAGIC   the MCP server queries.
# MAGIC - **Model/dimension consistency:** inline defaults to the 1024-dimension
# MAGIC   `databricks-gte-large-en` endpoint. If this graph holds data from more
# MAGIC   than one neocarta datasource, the inline model and dimension must match
# MAGIC   what the rest of neocarta uses, or cross-source vector search is
# MAGIC   inconsistent. You cannot mix inline and external embeddings on one graph
# MAGIC   without rebuilding the vector index. See the connector README.
