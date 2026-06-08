# Plan: Serve the dbxcarta Semantic Layer Through the Neocarta MCP Server

## Goal

The neocarta MCP server (`neocarta/_mcp/server.py`) exposes a Neo4j semantic-layer
graph to AI agents as a set of search tools. dbxcarta already builds a semantic-layer
graph in Neo4j from Databricks Unity Catalog. This plan describes how to point the
neocarta MCP server at a dbxcarta-produced graph — effectively "adding dbxcarta as a
new source" the MCP server can serve — and how to run a basic end-to-end test using
the finance-genie graph we already ingested.

---

## Architecture and Data Flow

Today there are two halves that have never been wired together: dbxcarta writes the
graph, and the neocarta MCP server reads a graph. They both speak Neo4j and, as it
turns out, use almost the same graph shape. The MCP server doesn't connect to
Databricks at all — it only talks to Neo4j. So "adding dbxcarta as a source" really
means "make the graph dbxcarta wrote look like the graph the MCP server expects to
read."

### Big picture

```
   WRITE SIDE (already working)                 READ SIDE (what we are wiring up)
   ----------------------------                 --------------------------------

  +---------------------------+                 +---------------------------+
  |   Databricks Unity        |                 |   AI agent / MCP client   |
  |   Catalog (silver+gold)   |                 |  (Claude Code, agent, ...) |
  +-------------+-------------+                 +-------------+-------------+
                |                                             | MCP tool calls
                v   dbxcarta-spark ingest                     v   (stdio)
  +---------------------------+                 +---------------------------+
  |  extract -> embed ->      |                 |   neocarta MCP server     |
  |  write nodes/edges        |                 |   (FastMCP, read-only)    |
  +-------------+-------------+                 +-------------+-------------+
                |                                             |
                |  writes graph + vector indexes             |  reads graph,
                v                                             v  runs vector / full-text
        +-------------------------------------------------------------+
        |                       Neo4j  (one graph)                     |
        |   Database -> Schema -> Table -> Column -> Value             |
        |   Column -REFERENCES-> Column                                |
        |   vector indexes on the `embedding` property                 |
        +-------------------------------------------------------------+
```

### What the MCP server does on a request

```
  user question
       |
       v
  [MCP server] embeds the question  ----> embedding model (must match dbxcarta's)
       |                                  produces a 1024-dim query vector
       v
  [Neo4j] db.index.vector.queryNodes('table_vector_index', k, queryVector)
       |   and/or db.index.fulltext.queryNodes('table_full_text_index', text)
       v
  seed Table/Column nodes
       |
       v
  expand: Schema, sibling Columns, sample Values, REFERENCES edges
       |
       v
  returns a compact schema/context block the agent uses to answer
```

The key idea: the agent's question is turned into a vector, that vector is compared
against the vectors dbxcarta already stored on each node, and the closest tables and
columns come back with their surrounding structure.

---

## What Already Lines Up (the good news)

dbxcarta and neocarta were converged on the same graph contract, so most of it
matches with no work:

- **Node labels match**: `Database`, `Schema`, `Table`, `Column`, `Value`.
- **Relationships match**: `HAS_SCHEMA`, `HAS_TABLE`, `HAS_COLUMN`, `HAS_VALUE`, `REFERENCES`.
- **Embedding property name matches**: both use `embedding` on the node.
- **Node properties the tools read are present**: `name`, `description`, and on
  `Column` also `type`, `nullable`, `is_primary_key`, `is_foreign_key`; `Value.value`.
- **Startup is not blocked**: the MCP server's version check only logs a warning if
  the dbxcarta graph has no `__neocarta_graph__` node — it does not refuse to start.

## What Needs Work (the gaps)

Three real differences stand between "graph exists" and "MCP tools return results":

1. **Vector index names differ.**
   - dbxcarta creates: `table_embedding`, `column_embedding`, `value_embedding`.
   - MCP queries by hardcoded name: `table_vector_index`, `column_vector_index`,
     `schema_vector_index`.
   - The MCP server decides *whether* to register a tool by detecting that a vector
     index exists on a label, but the tool's query calls the index *by name*. So a
     dbxcarta graph will register the tools and then fail at query time with
     "no such index `table_vector_index`". We must create indexes under the names the
     MCP server expects.

2. **No full-text indexes in dbxcarta.**
   - MCP full-text and hybrid tools query `table_full_text_index` and
     `column_full_text_index`. dbxcarta builds none. Without them, only the
     vector-search tools work. Creating them unlocks full-text and hybrid search.

3. **Embedding model / dimension must match.**
   - dbxcarta embeds with Databricks `databricks-gte-large-en` (1024 dimensions).
   - The MCP server defaults to OpenAI `text-embedding-3-small` (1536 dimensions).
   - The question must be embedded in the **same space** as the stored vectors, or
     vector search returns wrong results or errors on a dimension mismatch. The MCP
     server's embedding model is configurable, so we point it at the same Databricks
     model.

Not needed for a first test: `BusinessTerm` / `Glossary` nodes and `TAGGED_WITH`
edges. dbxcarta doesn't produce them, so the business-term tools simply won't
register — the server falls back to plain hybrid/vector/full-text. That's fine.

---

## Approach

There are two ways to close the gaps. Start with A to prove the flow; treat B as the
productized follow-up.

- **Approach A — graph adapter step (recommended for the initial test).**
  Leave both pipelines untouched. After a dbxcarta ingest, run a small one-time Cypher
  step against the same Neo4j graph that creates the indexes under the names the MCP
  server expects (vector, and optionally full-text). Then configure and launch the MCP
  server with the matching embedding model. Nothing in dbxcarta or neocarta code
  changes; the work is additive on the graph plus MCP configuration. Fastest path to a
  working demo.

- **Approach B — make it a first-class source (follow-up).**
  Two complementary options:
  - In the MCP server: make the index names and embedding model configurable in
    `settings.py` instead of hardcoding `table_vector_index` etc., so it can read a
    dbxcarta graph as-is.
  - In dbxcarta: add an optional "neocarta-compat" mode that emits the neocarta index
    names and writes a `__neocarta_graph__` version node at ingest time.
  Either removes the manual adapter step and makes the wiring permanent.

---

## Phased Implementation

### Phase 1 — Confirm the graph is present and embedded
- Use the finance-genie graph already ingested (see `integration-test.md`).
- Confirm nodes carry the `embedding` property and dbxcarta's vector indexes exist
  (`SHOW INDEXES`). Embeddings were enabled in the finance-genie overlay, so they
  should be there.

### Phase 2 — Add the indexes the MCP server expects (Approach A adapter)
- Create vector indexes under the neocarta names, on the `embedding` property,
  1024 dimensions, cosine:
  - `table_vector_index` on `(:Table)`
  - `column_vector_index` on `(:Column)`
  - optionally `schema_vector_index` on `(:Schema)` (only if schema embeddings exist)
- Optionally create full-text indexes to unlock hybrid search:
  - `table_full_text_index` on `Table(name, description)`
  - `column_full_text_index` on `Column(name, description)`
- These are additive; dbxcarta's own `*_embedding` indexes can stay.

### Phase 3 — Configure the MCP server
- Point it at the same Neo4j instance and database the dbxcarta job wrote to
  (`NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE=neo4j`).
- Set the embedding model to the same 1024-dim Databricks model dbxcarta used, via
  LiteLLM, plus Databricks auth. (Confirm the exact LiteLLM model string — expected to
  be `databricks/databricks-gte-large-en` with `DATABRICKS_API_BASE` /
  `DATABRICKS_API_KEY` — this is the main thing to verify in this phase.)

### Phase 4 — Launch and smoke-test
- Start `neocarta-mcp`, confirm the logs show a vector index inventory for `Table`
  and `Column`, then exercise the tools (see the test section below).

### Phase 5 — (Optional) make it permanent
- Decide between MCP-side config (configurable index names + embedding model) and
  dbxcarta-side compat mode, then move the Phase 2/3 steps into code so no manual
  adapter step is needed.

---

## How to Run an Initial Basic Test of the Flow

This reuses the finance-genie graph from `integration-test.md` (already in Neo4j with
1024-dim embeddings). The whole test is: add the expected indexes, start the server
with a matching embedding model, and confirm tools return finance tables.

**Step 1 — add the expected indexes (run once against the dbxcarta graph):**

```cypher
CREATE VECTOR INDEX table_vector_index IF NOT EXISTS
  FOR (n:Table) ON (n.embedding)
  OPTIONS {indexConfig: {`vector.dimensions`: 1024, `vector.similarity_function`: 'cosine'}};

CREATE VECTOR INDEX column_vector_index IF NOT EXISTS
  FOR (n:Column) ON (n.embedding)
  OPTIONS {indexConfig: {`vector.dimensions`: 1024, `vector.similarity_function`: 'cosine'}};

// optional, enables full-text + hybrid tools
CREATE FULLTEXT INDEX table_full_text_index IF NOT EXISTS
  FOR (n:Table) ON EACH [n.name, n.description];
CREATE FULLTEXT INDEX column_full_text_index IF NOT EXISTS
  FOR (n:Column) ON EACH [n.name, n.description];
```

**Step 2 — configure the MCP server environment** (same Neo4j as the ingest, matching
embedding model):

```
NEO4J_URI=neo4j+s://<the-finance-genie-instance>
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<password>
NEO4J_DATABASE=neo4j
EMBEDDING_MODEL=databricks/databricks-gte-large-en   # must produce 1024-dim vectors
DATABRICKS_API_BASE=https://dbc-cc887abc-9779.cloud.databricks.com/serving-endpoints
DATABRICKS_API_KEY=<token>
```

**Step 3 — start the server:** run the `neocarta-mcp` console script. On startup it
logs the detected index inventory; confirm it lists vector indexes for `Table` and
`Column` (and full-text if you created them).

**Step 4 — exercise the tools.** Easiest first check is to call the tools without a
full MCP client (catalog tools need no embeddings), then a vector search to prove the
embedding space lines up:

- `list_schemas` — should return the finance schema (`graph-enriched-schema`).
- `list_tables_by_schema` — should list `accounts`, `transactions`, `gold_accounts`,
  `gold_fraud_ring_communities`, etc.
- `get_full_metadata_schema` for one table — should return its columns with types.
- `get_context_by_table_vector_search` with a question like
  *"which accounts are part of a fraud ring?"* — should rank `gold_accounts` /
  `gold_fraud_ring_communities` near the top. This is the real end-to-end signal: it
  only works if the query embedding and the stored embeddings are in the same space.

**Step 5 — (optional) drive it as a real MCP client.** Register the server in an
`.mcp.json` so Claude Code connects to it, and ask a natural-language question that
forces a tool call. This confirms the full agent → MCP → Neo4j → answer path.

### What "passing" looks like
- Server starts and logs vector indexes for `Table` and `Column`.
- Catalog tools return the finance schema and tables.
- A vector-search tool returns the obviously relevant finance tables for a plain-English
  question, with no dimension-mismatch error.

---

## Risks and Open Questions

- **Embedding model string**: confirm the exact LiteLLM identifier and auth for the
  Databricks GTE endpoint, and that it returns 1024-dim vectors. This is the most
  likely thing to need a tweak. A dimension mismatch surfaces as a Neo4j vector-query
  error and is the first thing to check if search fails.
- **Index name coupling**: the MCP query Cypher hardcodes index names. Approach A works
  around this with extra indexes; Approach B should make the names configurable so the
  workaround isn't permanent.
- **Schema-level search**: `get_context_by_schema_and_table_vector_search` needs a
  `schema_vector_index`; only create it if dbxcarta wrote schema embeddings
  (`DBXCARTA_INCLUDE_EMBEDDINGS_SCHEMAS=true`, which finance-genie sets).
- **Version warning**: harmless for the test. To silence it, Approach B can write a
  `__neocarta_graph__` node during ingest.
- **Business-term tools**: absent by design here; revisit only if we later map a
  glossary onto the dbxcarta graph.
