# Semantic Layer MCP Server

An MCP server for semantic layer context retrieval, built to be compatible with the `neocarta` library. It connects to a Neo4j graph database containing your schema metadata and exposes tools for LLM agents to discover and retrieve relevant table and column context for query generation, query routing and data discovery tasks.

## Installation

```bash
pip install "neocarta[mcp]"
```

## Configuration

The server is configured via environment variables (or a `.env` file):

| Variable | Required | Default | Description |
|---|---|---|---|
| Provider credentials (`OPENAI_API_KEY`, `GEMINI_API_KEY`, `COHERE_API_KEY`, `AZURE_*`, `AWS_*`, …) | Yes | — | Auth for the embedding provider your `EMBEDDING_MODEL` targets. Read by LiteLLM at call time. |
| `NEO4J_URI` | Yes | — | Neo4j connection URI (e.g. `bolt://localhost:7687`) |
| `NEO4J_USERNAME` | Yes | — | Neo4j username |
| `NEO4J_PASSWORD` | Yes | — | Neo4j password |
| `NEO4J_DATABASE` | No | `neo4j` | Neo4j database name |
| `EMBEDDING_MODEL` | No | `text-embedding-3-small` | LiteLLM embedding model id (provider prefix optional for OpenAI) |
| `EMBEDDING_DIMENSIONS` | No | auto-detected | Vector dimension for models that support truncation; ignored by models that don't. Must match the dimension the graph was embedded at so query and stored vectors agree. |
| `SQL_DIALECT` | No | `bigquery` | sqlglot dialect `capture_task_memory` uses to canonicalize and parse captured SQL. Supported: `bigquery`, `snowflake`. |
| `DEFAULT_PROJECT_ID` | No | — | Default catalog for unqualified tables when `capture_task_memory` parses SQL (BigQuery: project; Snowflake: database). |
| `DEFAULT_SCHEMA_ID` | No | — | Default schema/dataset for unqualified tables (BigQuery: dataset; Snowflake: schema). |

The embedding vector dimension is auto-detected from the model — no manual configuration is needed. Set `EMBEDDING_DIMENSIONS` only if the graph was embedded at a non-native (truncated) size, so the server embeds queries at the same dimension; models that don't support truncation ignore it. `EMBEDDING_BATCH_SIZE` does **not** apply to the MCP server, which embeds a single query at a time.

## Running the server

```bash
uvx --from "neocarta[mcp]@0.8.0" neocarta-mcp
```

The server will only run in `stdio` transport mode and read all configuration parameters from the environment. 

In order for the semantic layer context to be utilized, the agent must also be capable of executing queries against the databases contained within the semantic layer graph.

## Tools

### `list_schemas`

Lists all schemas and the databases they belong to.

- **Input:** none
- **Output:** list of `{ schema_name, database_name }`
- **Use when:** an agent needs to orient itself before querying — useful as a first step to understand what schemas exist.

---

### `list_tables_by_schema`

Lists all tables within a given schema.

- **Input:** `schema_name: str`
- **Output:** list of `{ schema_name, table_names[] }`
- **Use when:** an agent knows which schema is relevant and wants to enumerate the tables available within it.

---

### `get_context_by_column_vector_search`

Finds the most relevant tables by computing semantic similarity between the query and **column embeddings** stored in the graph. Returns full table context including column descriptions, data types, example values, and foreign key references.

- **Input:**
  - `text_content: str` — a natural language question or keyword
  - `max_tables: int` — maximum number of tables to return (default: `5`)
- **Output:** list of `TableContext` (table + all columns, ordered by table name)
- **Retrieval:** queries `column_vector_index` (top 10 candidates, score threshold `> 0.5`), then traverses the graph to assemble full table context
- **Use when:** the query is likely to match at the column level — e.g. searching for a specific field like `"customer email"` or `"order total"`.

---

### `get_context_by_table_vector_search`

Finds the most relevant tables by computing semantic similarity between the query and **table embeddings** stored in the graph. Returns full table context including column descriptions, data types, example values, and foreign key references.

- **Input:**
  - `text_content: str` — a natural language question or keyword
  - `max_tables: int` — maximum number of tables to return (default: `10`)
- **Output:** list of `TableContext` (table + all columns, ordered by table name)
- **Retrieval:** queries `table_vector_index` (top 10 candidates, score threshold `> 0.5`), then traverses the graph to assemble full table context
- **Use when:** the query describes a general concept or entity rather than a specific field — e.g. `"customers"` or `"sales transactions"`.

---

### `get_context_by_schema_and_table_vector_search`

Finds the most relevant tables by computing semantic similarity against **schema and table embeddings**. Tables are ranked by schema relevance first, then table relevance, with a configurable cap on results.

- **Input:**
  - `text_content: str` — a natural language question or keyword
  - `max_tables: int` — maximum number of tables to return (default: `5`)
- **Output:** list of `TableContext` (ordered by schema score DESC, table score DESC)
- **Retrieval:** queries `schema_vector_index` (top 5 schemas, score threshold `> 0.5`), then filters tables where `table_score > schema_score - 0.2`
- **Use when:** the query is broad and may span multiple schemas — e.g. `"everything related to billing"`.

---

### `get_context_by_table_full_text_search` / `get_context_by_column_full_text_search`

Find tables by full-text matching on table or column name and description. Returns `TableContext` rows ordered by Lucene score (column variant aggregates matching columns up to their parent tables by average score). No embeddings required.

- **Retrieval:** queries `table_full_text_index` or `column_full_text_index` with the provided `text_content` (Lucene query syntax supported)
- **Use when:** the query contains literal tokens that should match table or column names/descriptions verbatim.

---

### `get_context_by_table_hybrid_search` / `get_context_by_column_hybrid_search`

Hybrid retrieval combining vector similarity and full-text search on the same node label. Scores from each branch are min-max normalized by the branch maximum and merged per node by taking the maximum.

- **Retrieval:** UNION of `*_vector_index` and `*_full_text_index` at the chosen label, then enrichment to `TableContext`
- **Use when:** the query mixes conceptual phrasing with literal tokens and you want both branches to vote.

---

### `get_context_by_table_business_term_hybrid_search` / `get_context_by_column_business_term_hybrid_search`

Hybrid retrieval whose full-text branch is bridged through `:BusinessTerm` tags: matching BusinessTerm nodes surface tables/columns that also match the query AND are connected via `TAGGED_WITH`. Combined with the vector branch through per-branch normalization and max-per-node merge.

- **Retrieval:** UNION of `*_vector_index` and `(businessterm_full_text_index + *_full_text_index where TAGGED_WITH)`, then enrichment to `TableContext`
- **Use when:** the query uses business-glossary phrasing (e.g. `"average order value"`) that may not appear verbatim in table/column metadata but is tagged to relevant nodes.

---

### Tool registration priority

At startup the MCP server probes the target database for its node-scoped search indexes and the presence of `:BusinessTerm` nodes. For each searchable label (Table, Column), the single highest-priority retrieval tool whose prerequisites are satisfied is registered:

1. `business_term_hybrid` — requires the label's vector and full-text indexes, the `businessterm_full_text_index`, and at least one `:BusinessTerm` node.
2. `hybrid` — requires the label's vector and full-text indexes.
3. `vector` or `full_text` — whichever index exists; if both exist, `hybrid` (or `business_term_hybrid`) wins.

Schema-level vector retrieval and catalog tools are registered independently when their prerequisites are met. The semantic-memory tools (`capture_task_memory`, `recall_task_memory`) are registered together when the `phrase_vector_index` is present — created by `neocarta memory init-indexes` (see the CLI README); otherwise they are skipped with a startup log hint.

---

### `get_full_metadata_schema`

Returns the complete metadata schema for all tables in the database, including all columns, data types, nullability, key types (primary/foreign), example values, and references.

- **Input:** none
- **Output:** list of `TableContext` for every table (ordered by table name)
- **Use when:** a complete picture of the schema is needed — e.g. for schema registration, evaluation baselines, or debugging. **This is an expensive query** and should almost never be used outside of development.

---

## Semantic memory: `recall_task_memory` & `capture_task_memory`

Two optional tools add a task-level memory over confirmed question→SQL pairs, so an agent can reuse a vetted query instead of rediscovering it. They register **only when the `phrase_vector_index` exists** — create it once with `neocarta memory init-indexes` (see the [CLI README](../_cli/README.md)), then restart the server.

**Graph model:** a `:Task:Memory` node (keyed by a CamelCase name) owns one or more `:Phrase` children (verbatim question wordings, each embedded) via `HAS_PHRASE`, and one or more canonical `:Query` nodes via `HAS_QUERY`; each `Query` links to the catalog `:Table` / `:Column` nodes it uses via `USES_TABLE` / `USES_COLUMN`. Only `:Phrase` nodes carry embeddings.

### `recall_task_memory`

Hybrid (vector + full-text) search over stored phrasings, rolled up to their `Task`. The vector and full-text branches are each min-max normalized by their own maximum and summed.

- **Input:** `question: str`, `top_k: int` (default `5`)
- **Output:** `{ candidates: RecalledMemory[], diagnostics: string | null }`. Each candidate carries `task_name`, `matched_phrase`, `phrasings[]`, `phrase_count`, `vector_score`, `hybrid_score`, `query_description`, `sql`, `tables[]`, `columns[]`.
- **Decision rule — gate on `vector_score`** (the raw cosine of the best-matching phrasing; `hybrid_score` orders candidates but is not calibrated): `>= 0.92` reuse the stored SQL as-is; `0.85–0.92` confirm with the user or use as a few-shot example; `< 0.85` treat as no hit and discover fresh.
- **`diagnostics`:** non-null when the vector branch was degraded (e.g. a `phrase_vector_index` embedding-dimension mismatch, or the embedding provider returned nothing). In that case `vector_score` is an unreliable `0` — do **not** apply the gate; surface the message instead.
- **Use when:** the FIRST step for any data question, before schema discovery.

### `capture_task_memory`

Persists a **user-confirmed** question/SQL pair. This is the only tool that writes to the graph (`RoutingControl.WRITE`).

- **Input:** `question: str`, `sql: str`, `description: str`, `name: str` (CamelCase merge key), `observations: string[]` (optional)
- **Output:** `CaptureMemoryResult` — `task_id`, `task_name`, `phrase_id`, `query_id`, `canonical_sql`, `linked_tables[]`, `linked_columns[]`, `unmatched_tables[]`, `unmatched_columns[]`
- **Behavior:** MERGEs the `Task` by `name` and attaches the question as an embedded `Phrase` (re-capturing the same name adds phrasings, raising future recall). The SQL is canonicalized before hashing, so alias-only, formatting, and predicate-order variants dedupe onto one canonical `Query`. The canonical SQL is parsed for `USES_TABLE` / `USES_COLUMN` links, using `SQL_DIALECT` / `DEFAULT_PROJECT_ID` / `DEFAULT_SCHEMA_ID` to stay warehouse-agnostic.
- **Use when:** ONLY after the user confirms an answer is correct — never on comparison runs or rejected answers. Non-empty `unmatched_tables` / `unmatched_columns` means the SQL touches catalog objects the semantic layer does not know about; surface them to the user.

### Claude Desktop

To connect the `neocarta-mcp` server to Claude Desktop, add the following entry to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "neocarta": {
      "command": "uvx",
      "args": [
        "--from",
        "neocarta[mcp]@0.8.0",
        "neocarta-mcp"
      ],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": "your-password",
        "NEO4J_DATABASE": "neo4j",
        "OPENAI_API_KEY": "sk-...",
        "EMBEDDING_MODEL": "text-embedding-3-small"
      }
    }
  }
}
```
