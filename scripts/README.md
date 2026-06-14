# Scripts

Helper scripts for working with neocarta outside the test suite.

## `test-neocarta-mcp.py` — MCP server smoke client

A standalone client that connects to a running neocarta MCP server over
streamable HTTP, lists every tool the server registered, and calls each one
with a sensible probe argument so you can confirm the server is healthy and
wired to a populated Neo4j database.

The neocarta MCP server registers tools dynamically. The catalog tools
(`list_schemas`, `list_tables_by_schema`, `get_full_metadata_schema`) are always
available; the search tools are registered only when the target database has the
matching indexes and `BusinessTerm` nodes. The client discovers the live tool
set at runtime rather than assuming it, so the exact set of tools it probes
depends on the data in your graph.

The client is the client only. It does not launch the server and reads no Neo4j
credentials. The server reads its own `NEO4J_*` and provider credentials from
the environment at startup.

### 1. Configure the server environment

The server reads its Neo4j connection and embedding provider credentials from
the environment (or a `.env` file). Copy the template and fill it in:

```bash
cp .env.example .env
# edit .env: set NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE,
# EMBEDDING_MODEL, and the provider key your model needs (e.g. OPENAI_API_KEY)
```

The graph must already be loaded with neocarta metadata. If it is empty the
server registers no tools and the client reports that.

### 2. Launch the server over HTTP (terminal 1)

The client speaks streamable HTTP, so start the server with `--http`:

```bash
uv run neocarta-mcp --http --port 8000
```

The server serves at `http://127.0.0.1:8000/mcp` by default. Use `--host`,
`--port`, and `--path` to change the bind address and endpoint. Without `--http`
the entry point runs over stdio instead, which is how an MCP client launches it
as a subprocess.

### 3. Run the client (terminal 2)

Point the client at the server URL:

```bash
uv run scripts/test-neocarta-mcp.py --url http://127.0.0.1:8000/mcp
```

Probe the search tools with a custom query instead of the default:

```bash
uv run scripts/test-neocarta-mcp.py --url http://127.0.0.1:8000/mcp \
    --query "customer orders revenue"
```

The script has inline [PEP 723](https://peps.python.org/pep-0723/) dependency
metadata, so `uv run` resolves the `mcp` client library on its own without a
prior `uv sync`.

### Output

The client runs in three steps:

1. Lists every registered tool with its description, input arguments, and
   required fields.
2. Probes each tool. Catalog tools are called with no arguments or a discovered
   schema name; search tools are called with the `--query` string. A tool whose
   required arguments cannot be auto-filled is skipped rather than failing the
   run.
3. Prints a summary of how many tools were listed, called successfully, failed,
   and skipped.

The process exits non-zero if any probed tool reports an error, which makes it
usable as a quick health check in a shell pipeline.
