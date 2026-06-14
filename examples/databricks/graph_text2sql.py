# Databricks notebook source
# MAGIC %md
# MAGIC # Databricks Connector: Graph-Retrieval Text2SQL
# MAGIC
# MAGIC This notebook turns a natural-language question into SQL by using the Neo4j
# MAGIC semantic graph to **find the relevant tables first**. The flow is:
# MAGIC
# MAGIC 1. Embed the question with the same Databricks model-serving endpoint used
# MAGIC    at ingest (`ai_query`), so the query vector lands in the same space as
# MAGIC    the stored node embeddings.
# MAGIC 2. Run a Neo4j **vector search** over `Table` nodes to retrieve the most
# MAGIC    semantically relevant tables, with their catalog, schema, columns, and a
# MAGIC    few sampled values.
# MAGIC 3. Assemble that into a compact schema context.
# MAGIC 4. Ask a Databricks foundation-model endpoint to write Spark SQL against
# MAGIC    only those tables, using fully-qualified `catalog.schema.table` names.
# MAGIC 5. Execute the generated SQL and show the result.
# MAGIC
# MAGIC This is the same retrieval pattern the neocarta MCP server exposes to AI
# MAGIC agents (`neocarta/_mcp/`); here it runs inline so you can read exactly what
# MAGIC each step does.
# MAGIC
# MAGIC **Assumes a graph built by `inline_embed_ingest.py`** (an inline-embedded
# MAGIC semantic graph with the per-label vector indexes). Unlike the ingest
# MAGIC notebook, this one talks to Neo4j through the **Neo4j Python driver**, not
# MAGIC the Neo4j Spark Connector, so it runs on serverless or classic compute. The
# MAGIC only cluster features it uses are `ai_query` (embedding + SQL generation)
# MAGIC and `spark.sql` (executing the generated query).

# COMMAND ----------

# MAGIC %md
# MAGIC ## Prerequisites
# MAGIC
# MAGIC - A populated, **inline-embedded** neocarta graph (run `inline_embed_ingest.py`
# MAGIC   first). The `table_vector_index` must exist.
# MAGIC - The **same embedding endpoint and dimension** used at ingest. Embedding the
# MAGIC   question with a different model or dimension makes the vector search
# MAGIC   meaningless. This notebook reuses the ingest endpoint to keep them aligned.
# MAGIC - A Databricks **foundation-model endpoint** for SQL generation (this notebook
# MAGIC   uses `databricks-claude-sonnet-4-6`).
# MAGIC - Permission to run the generated query against the ingested catalog (a SQL
# MAGIC   warehouse or cluster with access).

# COMMAND ----------

# MAGIC %md
# MAGIC ## Install the Neo4j driver
# MAGIC
# MAGIC Only the Neo4j Python driver is needed: the retrieval Cypher is inline in
# MAGIC this notebook, so there is no neocarta import. Restart Python so the install
# MAGIC takes effect; the restart clears notebook variables, so all configuration is
# MAGIC set *after* it, below.

# COMMAND ----------

# MAGIC %pip install neo4j

# COMMAND ----------

dbutils.library.restartPython()  # noqa: F821 — provided by the Databricks runtime

# COMMAND ----------

# MAGIC %md
# MAGIC ## Fill these in
# MAGIC
# MAGIC Everything the run needs is in this cell. (It is below the restart so the
# MAGIC values survive.)

# COMMAND ----------

# Neo4j connection (the graph built by inline_embed_ingest.py).
NEO4J_URI = "neo4j+s://<host>:7687"
NEO4J_USERNAME = "neo4j"
NEO4J_PASSWORD = "<password>"

# Must match the endpoint AND dimension used at ingest, or the question vector
# does not line up with the stored embeddings.
EMBEDDING_ENDPOINT = "openai-text-embedding-3-small"

# Databricks foundation-model endpoint used to generate the SQL.
LLM_ENDPOINT = "databricks-claude-sonnet-4-6"

# The natural-language question to answer.
QUESTION = "Which customers placed the most orders last month?"

# Retrieval knobs: how many table candidates the vector index returns, and how
# many tables to keep as SQL-generation context.
SEARCH_TOP_K = 10
MAX_TABLES = 5

# COMMAND ----------

# MAGIC %md
# MAGIC ## Embed the question
# MAGIC
# MAGIC Calls `ai_query` against the ingest-time embedding endpoint to turn the
# MAGIC question into a vector. The question text is passed as a bound parameter
# MAGIC (safe for any punctuation); the endpoint name is a literal because
# MAGIC `ai_query` requires a constant endpoint. Returns a `list[float]` to hand to
# MAGIC the Neo4j vector index.

# COMMAND ----------

row = spark.sql(  # noqa: F821 — spark provided by the runtime
    f"SELECT ai_query('{EMBEDDING_ENDPOINT}', :q) AS embedding",
    args={"q": QUESTION},
).collect()[0]
query_embedding = [float(x) for x in row["embedding"]]

print(f"embedded question into a {len(query_embedding)}-dim vector")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Find relevant tables (Neo4j vector search)
# MAGIC
# MAGIC Queries the `table_vector_index` for the tables most similar to the
# MAGIC question, then walks the graph to gather each table's catalog, schema, and
# MAGIC columns (with a few sampled values). This is a readable, single-strategy
# MAGIC version of the table vector search in
# MAGIC `neocarta/_mcp/cypher/vector_search.py`. Values are collapsed per column
# MAGIC first, then columns are collapsed per table (Cypher cannot nest `collect`).

# COMMAND ----------

from neo4j import GraphDatabase

TABLE_VECTOR_SEARCH = """
// Most semantically similar tables for the question vector.
CALL db.index.vector.queryNodes('table_vector_index', $searchTopK, $queryEmbedding)
YIELD node AS table, score AS tableScore
WHERE tableScore > 0.5

// Structural context: which catalog/schema each table belongs to.
MATCH (db:Database)-[:HAS_SCHEMA]->(schema:Schema)-[:HAS_TABLE]->(table)
MATCH (table)-[:HAS_COLUMN]->(col:Column)

// A few example values per column (optional; Value nodes may not exist).
OPTIONAL MATCH (col)-[:HAS_VALUE]->(v:Value)
WITH table, schema, tableScore, col,
     collect(DISTINCT v.value)[0..3] AS examples

// Collapse columns into one row per table.
WITH table, schema, tableScore,
     collect({
         name: col.name,
         type: col.type,
         description: col.description,
         examples: examples
     }) AS columns

RETURN table.catalog      AS catalog,
       schema.name        AS schema_name,
       table.name         AS table_name,
       table.description  AS description,
       columns,
       tableScore         AS score
ORDER BY score DESC
LIMIT $maxTables
"""


def retrieve_tables(question_embedding: list[float]) -> list[dict]:
    """Return the most relevant tables for the embedded question.

    Each result is a dict with ``catalog``, ``schema_name``, ``table_name``,
    ``description``, ``columns`` (list of column dicts), and ``score``.
    """
    with GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD)) as driver:
        records, _, _ = driver.execute_query(
            TABLE_VECTOR_SEARCH,
            queryEmbedding=question_embedding,
            searchTopK=SEARCH_TOP_K,
            maxTables=MAX_TABLES,
        )
    return [record.data() for record in records]


tables = retrieve_tables(query_embedding)

for table in tables:
    print(f"{table['score']:.3f}  {table['catalog']}.{table['schema_name']}.{table['table_name']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Assemble the schema context
# MAGIC
# MAGIC Formats the retrieved tables into a compact, DDL-like block the model can
# MAGIC read: one fully-qualified table per section, then each column with its type,
# MAGIC description, and a few example values.

# COMMAND ----------


def format_schema_context(retrieved_tables: list[dict]) -> str:
    """Render retrieved tables as a compact schema description for the prompt."""
    blocks = []
    for table in retrieved_tables:
        fqn = f"{table['catalog']}.{table['schema_name']}.{table['table_name']}"
        lines = [f"Table: {fqn}"]
        if table.get("description"):
            lines.append(f"  -- {table['description']}")
        for col in table["columns"]:
            line = f"  {col['name']} {col['type'] or ''}".rstrip()
            notes = []
            if col.get("description"):
                notes.append(col["description"])
            if col.get("examples"):
                notes.append("examples: " + ", ".join(str(v) for v in col["examples"]))
            if notes:
                line += "  -- " + "; ".join(notes)
            lines.append(line)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


schema_context = format_schema_context(tables)
print(schema_context)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Generate the SQL
# MAGIC
# MAGIC Sends the question and the retrieved schema to the foundation-model
# MAGIC endpoint and asks for a single Spark SQL statement that uses only those
# MAGIC tables, with fully-qualified `catalog.schema.table` names. Any Markdown code
# MAGIC fence the model adds is stripped off.

# COMMAND ----------

import re

PROMPT_TEMPLATE = """You are a Spark SQL expert. Write a single Spark SQL query that answers the question.

Rules:
- Use ONLY the tables and columns listed below.
- Always use fully-qualified names: catalog.schema.table.
- Return only the SQL, with no explanation and no markdown fences.

Schema:
{schema}

Question: {question}
"""


def generate_sql(question: str, schema: str) -> str:
    """Generate a Spark SQL statement from the question and schema context."""
    prompt = PROMPT_TEMPLATE.format(schema=schema, question=question)
    result = spark.sql(  # noqa: F821 — spark provided by the runtime
        f"SELECT ai_query('{LLM_ENDPOINT}', :prompt) AS sql",
        args={"prompt": prompt},
    ).collect()[0]
    # Strip a leading ```sql / trailing ``` fence if the model added one.
    return re.sub(r"^```(?:sql)?\s*|\s*```$", "", result["sql"].strip(), flags=re.IGNORECASE)


generated_sql = generate_sql(QUESTION, schema_context)
print(generated_sql)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run the generated SQL
# MAGIC
# MAGIC The query is generated by an LLM and runs against live data. **Review it
# MAGIC above before running this cell.** The retrieval and prompt steer toward
# MAGIC read-only `SELECT`s, but nothing here enforces that, so inspect the
# MAGIC statement first.

# COMMAND ----------

display(spark.sql(generated_sql))  # noqa: F821 — spark/display provided by the runtime

# COMMAND ----------

# MAGIC %md
# MAGIC ## What next
# MAGIC
# MAGIC - This is the inline version of what the neocarta **MCP server** does for AI
# MAGIC   agents (`neocarta/_mcp/`), and what the LangChain/LangGraph Text2SQL agent
# MAGIC   in `agent/` drives. The production Cypher also surfaces `REFERENCES` edges
# MAGIC   (foreign keys) so generated SQL can join across tables, and offers
# MAGIC   column-level and hybrid (vector + full-text) retrieval strategies.
# MAGIC - **Model/dimension consistency:** the question must be embedded with the
# MAGIC   same model and dimension used to embed the graph. This notebook reuses the
# MAGIC   ingest `EMBEDDING_ENDPOINT` precisely so they match.
# MAGIC - The vector indexes created at ingest are named `table_vector_index`,
# MAGIC   `column_vector_index` (lowercase) — the names this notebook and the MCP
# MAGIC   layer query.
