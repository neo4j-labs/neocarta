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
| `OPENAI_API_KEY` | Yes | — | OpenAI API key for embedding generation |
| `NEO4J_URI` | Yes | — | Neo4j connection URI (e.g. `bolt://localhost:7687`) |
| `NEO4J_USERNAME` | Yes | — | Neo4j username |
| `NEO4J_PASSWORD` | Yes | — | Neo4j password |
| `NEO4J_DATABASE` | No | `neo4j` | Neo4j database name |
| `EMBEDDING_MODEL` | No | `text-embedding-3-small` | OpenAI embedding model |
| `EMBEDDING_DIMENSIONS` | No | `768` | Embedding vector dimensions |

## Running the server

```bash
uvx --from "neocarta[mcp]@0.3.0" neocarta-mcp
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

### `get_metadata_schema_by_column_semantic_similarity`

Finds the most relevant tables by computing semantic similarity between the query and **column embeddings** stored in the graph. Returns full table context including column descriptions, data types, example values, and foreign key references.

- **Input:**
  - `text_content: str` — a natural language question or keyword
  - `max_tables: int` — maximum number of tables to return (default: `5`)
- **Output:** list of `TableContext` (table + all columns, ordered by table name)
- **Retrieval:** queries `column_vector_index` (top 10 candidates, score threshold `> 0.5`), then traverses the graph to assemble full table context
- **Use when:** the query is likely to match at the column level — e.g. searching for a specific field like `"customer email"` or `"order total"`.

---

### `get_metadata_schema_by_table_semantic_similarity`

Finds the most relevant tables by computing semantic similarity between the query and **table embeddings** stored in the graph. Returns full table context including column descriptions, data types, example values, and foreign key references.

- **Input:**
  - `text_content: str` — a natural language question or keyword
  - `max_tables: int` — maximum number of tables to return (default: `10`)
- **Output:** list of `TableContext` (table + all columns, ordered by table name)
- **Retrieval:** queries `table_vector_index` (top 10 candidates, score threshold `> 0.5`), then traverses the graph to assemble full table context
- **Use when:** the query describes a general concept or entity rather than a specific field — e.g. `"customers"` or `"sales transactions"`.

---

### `get_metadata_schema_by_schema_and_table_semantic_similarity`

Finds the most relevant tables by computing semantic similarity against **schema and table embeddings**. Tables are ranked by schema relevance first, then table relevance, with a configurable cap on results.

- **Input:**
  - `text_content: str` — a natural language question or keyword
  - `max_tables: int` — maximum number of tables to return (default: `5`)
- **Output:** list of `TableContext` (ordered by schema score DESC, table score DESC)
- **Retrieval:** queries `schema_vector_index` (top 5 schemas, score threshold `> 0.5`), then filters tables where `table_score > schema_score - 0.2`
- **Use when:** the query is broad and may span multiple schemas — e.g. `"everything related to billing"`.

---

### `get_full_metadata_schema`

Returns the complete metadata schema for all tables in the database, including all columns, data types, nullability, key types (primary/foreign), example values, and references.

- **Input:** none
- **Output:** list of `TableContext` for every table (ordered by table name)
- **Use when:** a complete picture of the schema is needed — e.g. for schema registration, evaluation baselines, or debugging. **This is an expensive query** and should almost never be used outside of development.

### Claude Desktop

To connect the `neocarta-mcp` server to Claude Desktop, add the following entry to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "neocarta": {
      "command": "uvx",
      "args": [
        "--from",
        "neocarta[mcp]@0.3.0",
        "neocarta-mcp"
      ],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": "your-password",
        "NEO4J_DATABASE": "neo4j",
        "OPENAI_API_KEY": "sk-...",
        "EMBEDDING_MODEL": "text-embedding-3-small",
        "EMBEDDING_DIMENSIONS": "768"
      }
    }
  }
}
```
