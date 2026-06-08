# dbxcarta × Neocarta MCP — v2

## Overview (TLDR)

dbxcarta now writes a Neo4j graph that the **neocarta MCP server reads directly**, with no
compatibility layer. The plan in `examples/finance-genie/mcp.md` is implemented: dbxcarta's
index names, full-text and range indexes, version node, and embedding model were all cut over
to match what the MCP server expects. A dbxcarta job builds the graph; `neocarta-mcp` serves
it to AI agents over stdio or HTTP. The two sides share the same index names and the same
embedding space, so vector and full-text search resolve and return sensible results.

What was completed:

- **Vector indexes renamed** from `<label>_embedding` to `<label>_vector_index` (Table,
  Column, Schema, Database). `Value` dropped from the vector set; Value nodes still traverse via
  `HAS_VALUE`.
- **Full-text indexes added**: `table_full_text_index`, `column_full_text_index` over
  `name` + `description`.
- **Name range indexes added**: `database_name_index`, `schema_name_index`,
  `table_name_index`, `column_name_index` on `name`.
- **`__neocarta_graph__` version node** upserted on every ingest, mirroring neocarta's
  `upsert_neocarta_graph_node`, so the MCP server's writer/reader version check passes instead
  of warning.
- **Embedding model aligned** to OpenAI `text-embedding-3-small` at **1536 dims** through a
  Databricks External-Models serving endpoint, so dbxcarta's stored vectors and the MCP's query
  vectors live in the same space.

Where it lives in code:

- `dbxcarta-spark/src/dbxcarta/spark/ingest/load/neo4j_io.py` —
  `bootstrap_constraints` (indexes) and `upsert_neocarta_graph_node` (version node).
- `dbxcarta-spark/src/dbxcarta/spark/run.py` — calls both during ingest.
- `examples/finance-genie/dbxcarta-overlay.env` — sets the embedding endpoint and dimension.

New scripts:

- `setup_secrets.sh` (repo root) — provisions the Databricks Neo4j and OpenAI secret scopes
  from each example's overlay + standalone `.env`.
- `scripts/setup-openai-endpoint.py` — creates and verifies the OpenAI External-Models
  embedding endpoint, idempotent, with a 1536-dim probe.
- `scripts/test-neocarta-mcp.py` — connects to a separately running MCP server over HTTP and
  exercises every registered tool.
- `scripts/run_autotest.py` — full end-to-end ingest + assertion harness.
- `scripts/run_demo.py`, `scripts/clean-dbxcarta.py` — demo catalog setup and ops-plane cleanup.

---

## ELI5: why "OpenAI External-Models" at all?

**The problem.** Search works by turning text into a list of numbers called an *embedding*.
dbxcarta turns each table and column into numbers and stores them in Neo4j. The MCP server
turns the user's question into numbers and looks for the closest matches. For "closest" to mean
anything, **both sides have to use the exact same number-making machine**. If dbxcarta uses one
machine and the MCP server uses another, the two sets of numbers are not comparable, and search
either errors out or returns nonsense.

**The mismatch.** dbxcarta originally made its numbers with a Databricks model
(`databricks-gte-large-en`, 1024 numbers each). The neocarta MCP server defaults to an OpenAI
model (`text-embedding-3-small`, 1536 numbers each). Different machine, different count, so the
numbers do not line up.

**The fix.** Make both sides use OpenAI's `text-embedding-3-small`. The MCP server already does.
The catch is that dbxcarta runs **inside Databricks**, and the ingest job is not supposed to
reach out to the public internet or juggle an OpenAI key on its own.

**What an External-Models endpoint is.** Databricks lets you create a serving endpoint that is
just a **labeled doorway inside your workspace that forwards requests to an outside provider**
like OpenAI. You set it up once: provider `openai`, model `text-embedding-3-small`, and your
OpenAI key stored as a Databricks secret. After that, anything in the workspace calls the
endpoint **by name**, exactly like a built-in Databricks model, and gets back the same numbers
OpenAI would return directly.

**Why it is the clean answer.** dbxcarta keeps calling "an endpoint by name" the way it always
has. Nothing in the pipeline learns about OpenAI. The key stays in a Databricks secret instead
of in config or job parameters. And because the doorway points at the **same** OpenAI model the
MCP server uses, both sides finally make their numbers with the same machine, so search lines up.

(If you would rather not stand up an endpoint, the alternative is to keep the Databricks-native
model and point the MCP server at *that* instead. Same principle, opposite direction: match the
two sides. See the configuration section below.)

---

## What needs to be done next (testing)

**Status: verified end to end on 2026-06-08.** Items 1-4 below were executed against the live
finance-genie graph and passed; item 5 remains optional. The exact commands and results are in
the [Work log (2026-06-08)](#work-log-2026-06-08) section at the bottom of this doc.

The cutover code is in place. The remaining work is to run it against a live graph and confirm
the read side:

1. **Re-ingest the finance-genie catalog** with the new contract so the graph is rebuilt with
   the renamed indexes, the 1536-dim vectors, and the version node. Old 1024-dim vectors are not
   reusable, so re-embedding is required.
2. **Confirm index inventory at MCP startup** — the server should log vector indexes for
   `Table` and `Column` (plus `Schema` and the full-text indexes) and a version **match**, not
   the "no `__neocarta_graph__`" warning.
3. **Exercise the catalog tools** (`list_schemas`, `list_tables_by_schema`,
   `get_full_metadata_schema`) — they need no embeddings and confirm the graph shape.
4. **Exercise vector search** (`get_context_by_table_vector_search`) with a plain-English
   finance question and confirm the relevant tables rank near the top with no
   dimension-mismatch error. This is the real end-to-end signal.
5. **Optional**: register the server in `.mcp.json` and drive it from a real MCP client to
   confirm the full agent → MCP → Neo4j path.

Open items to watch: the embedding dimension must agree on all three of model output, any
`dimensions` shrink param, and the Neo4j index; the `schema_vector_index` only exists when
schema embeddings are enabled (finance-genie sets this); `businessterm_full_text_index` is
intentionally absent because dbxcarta has no BusinessTerm nodes, so those tools simply do not
register.

---

## Configuring and running the neocarta MCP server

The MCP server never talks to Databricks. It only reads Neo4j. Point it at the same Neo4j
instance the dbxcarta job wrote to, with an embedding model matching what dbxcarta used. It
reads its config from a `.env` file via `load_dotenv()` at startup, so configure it through a
`.env` rather than exporting variables by hand. The neocarta repo-root `.env.example` is a
ready-made template: `cp .env.example .env` and fill in these keys.

```dotenv
NEO4J_URI=neo4j+s://<the-finance-genie-instance>
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<password>
NEO4J_DATABASE=neo4j

# Embedding (must match the model dbxcarta embedded with)
EMBEDDING_MODEL=text-embedding-3-small
OPENAI_API_KEY=<key>
```

Start it with the `neocarta-mcp` console script (entry point `neocarta._mcp.server:run`). It has
two transports:

- **stdio (default)** — `uv run neocarta-mcp`. An MCP client launches the server as a subprocess
  and talks over stdin/stdout. There is no URL; the client owns the process.
- **streamable HTTP** — `uv run neocarta-mcp --http [--host 127.0.0.1] [--port 8000] [--path
  /mcp]`. The server runs independently and any client connects by URL. Use this when you want
  the server up on its own, as the test script below does.

On startup, either way, it probes the database, then registers only the tools whose indexes
exist. Catalog tools always register; search tools depend on the indexes present.

### Does anything change now that dbxcarta is updated?

**The MCP server config itself does not change** — it already defaulted to
`text-embedding-3-small`. What changed is that **the graph dbxcarta writes now satisfies the
server's expectations**, so the server behaves differently against a freshly ingested graph:

- The vector tools for `Table`, `Column`, and `Schema` now register, because the indexes are
  named what the server queries (`<label>_vector_index`).
- The full-text and hybrid tools for `Table` and `Column` now register.
- The version check logs a **match** instead of the missing-node warning.
- Vector queries return meaningful results, because both sides now use the same 1536-dim model.

If you keep the Databricks-native model instead of OpenAI, set
`EMBEDDING_MODEL=databricks/databricks-gte-large-en` with `DATABRICKS_API_BASE` /
`DATABRICKS_API_KEY`, and make sure dbxcarta's `DBXCARTA_EMBEDDING_DIMENSION` and the Neo4j
index dimension both match that model.

---

## Using the dbxcarta MCP test scripts

### `scripts/test-neocarta-mcp.py` — probe a running server over HTTP

The client and server are separated. You launch the server independently over HTTP, then run
this script as a pure client against its URL. The script never launches the server and reads no
Neo4j credentials; the server resolves its own connection from its `.env` via `load_dotenv()`,
exactly as it does in production. Set up that `.env` once as shown under "Configuring and running
the neocarta MCP server" above.

It connects to the `--url` you give, lists every registered tool with its schema, then calls
each one with a probe argument and prints a short preview. The registered tool set is discovered
at runtime rather than assumed, so it reflects exactly which indexes the target database has.

```bash
# one-time — create the server's .env from the template and fill in the values
cp .env.example .env   # then set NEO4J_* and OPENAI_API_KEY

# terminal 1 — launch the server independently over HTTP.
# It reads NEO4J_* / OPENAI_API_KEY from .env via load_dotenv() at startup.
uv run neocarta-mcp --http --port 8000

# terminal 2 — connect the client and probe every tool (--url is required)
uv run scripts/test-neocarta-mcp.py --url http://127.0.0.1:8000/mcp

# probe the search tools with a custom query string
uv run scripts/test-neocarta-mcp.py --url http://127.0.0.1:8000/mcp \
  --query "which accounts are part of a fraud ring?"
```

A healthy run lists the catalog tools plus the `Table` / `Column` vector and full-text tools,
and every probe returns a result preview with no dimension-mismatch error.

### `scripts/run_autotest.py` — full ingest + assertion harness

Runs the broader end-to-end path: preflight connectivity, unit tests, schema setup, an ingest
submit, assertions against the run summary, and a fixture-vs-Neo4j `REFERENCES` diff. Use this
to validate the write side before pointing the MCP server at the graph.

```bash
uv run python scripts/run_autotest.py
```

### Supporting scripts

- `setup_secrets.sh --profile <profile> --example finance-genie` — provision the Neo4j and
  OpenAI secret scopes before the first ingest.
- `scripts/setup-openai-endpoint.py --profile <profile> --warehouse-id <id>` — create and
  verify the OpenAI embedding endpoint (Steps B and C in `mcp.md`).
- `scripts/run_demo.py` — set up the demo catalog schemas against a SQL warehouse.
- `scripts/clean-dbxcarta.py` — tear down one integration's ops plane.

Order for a clean run: `setup_secrets.sh` → `setup-openai-endpoint.py` → ingest → 
`test-neocarta-mcp.py`.

---

## Work log (2026-06-08)

Verified the read side end to end against the live finance-genie graph
(`neo4j+s://4b2239bb.databases.neo4j.io`). The server ran over HTTP; the test script connected
as a client and probed every registered tool. Both finance queries passed with no
dimension-mismatch error, which confirms the 1536-dim embedding alignment on both sides.

### Commands run

```bash
# terminal 1 — launch the server over HTTP in the background.
# It read NEO4J_* / OPENAI_API_KEY from the repo-root .env via load_dotenv() at startup.
uv run neocarta-mcp --http --port 8000

# terminal 2 — probe every tool with the default query
uv run scripts/test-neocarta-mcp.py --url http://127.0.0.1:8000/mcp

# terminal 2 — probe every tool with a finance-specific query
uv run scripts/test-neocarta-mcp.py --url http://127.0.0.1:8000/mcp \
  --query "which accounts are part of a fraud ring?"
```

### Server startup (item 2 — index inventory + version check)

The server logged a **version match** and the expected index inventory, with `BusinessTerm`
correctly absent:

```
INFO  Neocarta graph metadata version 0.6.0 server.py:105 matches MCP server version.
INFO  Detected search indexes: [('Column', 'FULLTEXT'), ('Column', 'VECTOR'),
      ('Database', 'VECTOR'), ('Schema', 'VECTOR'), ('Table', 'FULLTEXT'), ('Table', 'VECTOR')]
INFO  BusinessTerm full-text index present=False, BusinessTerm nodes present=False
INFO  Registered schema vector tool
INFO  Registered hybrid tool for Table
INFO  Registered hybrid tool for Column
INFO  Starting MCP server 'Neocarta MCP Server' with transport 'http' on http://127.0.0.1:8000/mcp
```

This satisfies item 2: vector indexes for `Table`, `Column`, `Schema`, and `Database`, full-text
for `Table` and `Column`, a version **match** rather than the missing-node warning, and no
BusinessTerm tools (dbxcarta has no BusinessTerm nodes, as designed).

### Six tools registered

The server registered exactly the tools the live graph supports, discovered at runtime:

| Tool | Type |
| --- | --- |
| `list_schemas` | catalog |
| `list_tables_by_schema` | catalog |
| `get_full_metadata_schema` | catalog |
| `get_context_by_schema_and_table_vector_search` | vector |
| `get_context_by_table_hybrid_search` | hybrid (vector + full-text) |
| `get_context_by_column_hybrid_search` | hybrid (vector + full-text) |

### Probe results

Both runs ended with **6 tools listed, 6 called ok, 0 failed, 0 skipped.**

**Catalog tools (item 3)** returned the real graph shape:

- `list_schemas` → two databases (`graph-enriched-finance-gold`, `graph-enriched-finance-silver`),
  both under `graph-enriched-schema`.
- `list_tables_by_schema` → `accounts`, `transactions`, `account_links`, `merchants`,
  `account_labels`, `gold_accounts`, `gold_fraud_ring_communities`,
  `gold_account_similarity_pairs`.
- `get_full_metadata_schema` → full column detail, including `references` (FK edges) such as
  `account_labels.account_id → accounts.account_id`.

**Search tools (item 4 — the real end-to-end signal)** ranked the relevant tables at the top,
which proves the stored vectors and the query vectors share the same 1536-dim space:

- Query `"customer orders and revenue"` → vector and table-hybrid both surfaced `merchants`;
  column-hybrid surfaced `transactions`.
- Query `"which accounts are part of a fraud ring?"` → vector search ranked
  `gold_fraud_ring_communities` first; column-hybrid surfaced `account_labels` with the
  `is_fraud` column at `column_avg_score 1.0`, then `gold_fraud_ring_communities`.

### Result

Items 1-4 are confirmed: the graph is ingested under the new contract (version node + renamed
indexes are live), the index inventory and version check are correct at startup, the catalog
tools return the real shape, and vector and full-text search return semantically relevant tables
with no dimension-mismatch error. Item 5 (drive from a real MCP client via `.mcp.json`) remains
optional and was not run.
