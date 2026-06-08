# Plan: Cut dbxcarta Over to the Neocarta MCP Server Contract

## Goal

The neocarta MCP server (`neocarta/_mcp/server.py`) exposes a Neo4j semantic-layer
graph to AI agents as search tools. dbxcarta builds the same kind of graph from
Databricks Unity Catalog. This plan makes dbxcarta write a graph that the neocarta MCP
server can read directly.

This is a **hard cutover**. There are no existing clients of the dbxcarta graph, so we
do not keep the old index names, add aliases, or build any compatibility layer.
dbxcarta changes to match neocarta exactly, and the old names are deleted.

---

## Architecture and Data Flow

The MCP server never talks to Databricks. It only talks to Neo4j. So aligning the two
is about making the graph dbxcarta writes match the graph the MCP server reads.

```
   WRITE SIDE (dbxcarta)                         READ SIDE (neocarta MCP)
   ----------------------                        ------------------------

  Databricks Unity Catalog                       AI agent / MCP client
          |                                               |  tool calls (stdio)
          v  dbxcarta-spark ingest                        v
  extract -> embed -> write  --------+      +----  neocarta MCP server (read-only)
                                     |      |
                                     v      v
              +-------------------------------------------------+
              |                  Neo4j (one graph)              |
              |  Database -> Schema -> Table -> Column -> Value |
              |  Column -REFERENCES-> Column                    |
              |  indexes the MCP queries BY NAME                |
              |  + __neocarta_graph__ version node              |
              +-------------------------------------------------+
```

On each request the MCP server embeds the user's question, runs a vector and/or
full-text query against indexes it calls **by hardcoded name**, then expands the seed
nodes into surrounding schema. Two things therefore have to match exactly: the **index
names**, and the **embedding model** used to turn the question into a vector (it must be
the same model dbxcarta used to embed the nodes).

---

## What Already Aligns (no change needed)

The two pipelines were converged on the same graph contract, so the graph *shape* is
already identical:

- **Node labels**: `Database`, `Schema`, `Table`, `Column`, `Value`.
- **Relationship types**: `HAS_SCHEMA`, `HAS_TABLE`, `HAS_COLUMN`, `HAS_VALUE`, `REFERENCES`.
- **Every node property the MCP reads** already exists on dbxcarta nodes:
  - Database: `name`
  - Schema: `name`, `embedding`
  - Table: `id`, `name`, `description`, `embedding`
  - Column: `id`, `name`, `description`, `type`, `nullable`, `is_primary_key`, `is_foreign_key`, `embedding`
  - Value: `value`
- **id-uniqueness constraints** — the MCP does not reference these by name, so dbxcarta's
  `database_id` / `schema_id` / ... constraints stay as they are.

So there are **no node field renames**. The cutover lives entirely in the index,
metadata-node, and embedding layers below.

---

## What Must Change in dbxcarta (the cutover list)

All index creation lives in
`dbxcarta/dbxcarta-spark/src/dbxcarta/spark/ingest/load/neo4j_io.py`
(`bootstrap_constraints`). The neocarta canonical DDL it must match lives in
`neocarta/ingest/indexes.py` and `neocarta/ingest/metadata.py`.

### 1. Rename the vector indexes  (the core change)

dbxcarta names them `<label>_embedding`; neocarta names them `<label>_vector_index`.
The MCP query Cypher calls the neocarta names, so the dbxcarta names must be replaced.

| Node label | dbxcarta name now | neocarta target name | MCP queries it? |
|------------|-------------------|----------------------|-----------------|
| Table      | `table_embedding`    | `table_vector_index`    | yes (`table_vector_index`) |
| Column     | `column_embedding`   | `column_vector_index`   | yes (`column_vector_index`) |
| Schema     | `schema_embedding`   | `schema_vector_index`   | yes (`schema_vector_index`) |
| Database   | `database_embedding` | `database_vector_index` | no (no DB vector tool, but keep for parity) |
| Value      | `value_embedding`    | **removed**             | no (neocarta defines no Value vector index) |

- Code change: in the vector-index loop, change the suffix `_embedding` to
  `_vector_index`.
- Remove `Value` from the vector-index set. neocarta's `create_vector_index` supports
  only Database/Schema/Table/Column, and the MCP never vector-searches `Value`. Value
  nodes are still returned via `HAS_VALUE` traversal using the `value` property.
- The embedding property stays `embedding` (already matches).

### 2. Add full-text indexes  (new — dbxcarta builds none today)

The MCP full-text and hybrid tools query these by name, over `name` + `description`:

| neocarta target name        | Definition |
|-----------------------------|------------|
| `table_full_text_index`     | `FOR (n:Table) ON EACH [n.name, n.description]` |
| `column_full_text_index`    | `FOR (n:Column) ON EACH [n.name, n.description]` |

- `businessterm_full_text_index` is **not** created — dbxcarta has no BusinessTerm
  nodes, and those tools simply will not register. That is expected.

### 3. Add name range indexes  (new — parity + catalog-tool performance)

neocarta creates a `<label>_name_index` range index on `name` for every catalog label,
so the MCP catalog tools' exact-name lookups (`MATCH (n:Label {name: $value})`) seek
instead of scan:

| neocarta target name   | Definition |
|------------------------|------------|
| `database_name_index`  | `FOR (n:Database) ON (n.name)` |
| `schema_name_index`    | `FOR (n:Schema) ON (n.name)` |
| `table_name_index`     | `FOR (n:Table) ON (n.name)` |
| `column_name_index`    | `FOR (n:Column) ON (n.name)` |

- Catalog tools still return correct results without these, but add them for full
  neocarta parity and to avoid label scans on large catalogs.
- dbxcarta's existing `column_type` and `value_last_run` indexes are dbxcarta-internal,
  unused by the MCP, and harmless — leave them.

### 4. Write the `__neocarta_graph__` version node  (new)

The MCP server reads a singleton `:__neocarta_graph__` node to check writer/reader
versions. If it is missing the server only logs a warning (it still runs), but for a
true cutover dbxcarta must write it, mirroring
`neocarta/ingest/metadata.py:upsert_neocarta_graph_node`:

- Label: `__neocarta_graph__`
- Properties: `initial_version`, `latest_version` (set to the neocarta library version
  the MCP server runs), `create_date`, `last_updated` (datetimes).
- Upsert pattern: `ON CREATE` stamps initial_version + create_date; `ON MATCH` refreshes
  latest_version + last_updated.

### 5. Align the embedding model and dimension  (see next section)

Stored node vectors and the MCP's query vectors must come from the **same model** and be
the **same dimension**, or vector search errors out or returns nonsense.

- dbxcarta currently: `databricks-gte-large-en`, 1024 dimensions
  (`DBXCARTA_EMBEDDING_ENDPOINT`, `DBXCARTA_EMBEDDING_DIMENSION`).
- neocarta MCP default: `text-embedding-3-small`, 1536 dimensions (`EMBEDDING_MODEL`).
- The vector index dimension dbxcarta creates must equal the embedding dimension on both
  sides.

---

## Embedding: Does Databricks Support OpenAI Embedding Models?

**Yes.** Databricks Mosaic AI Model Serving has an **External Models** feature (the AI
Gateway) that lets you create a serving endpoint which proxies a third-party provider.
You create an endpoint with provider `openai`, task `llm/v1/embeddings`, model
`text-embedding-3-small` (or `-large`, or `ada-002`), and your OpenAI API key stored in
a Databricks secret. Anything in the workspace — including dbxcarta — then calls that
endpoint by name like any native serving endpoint, and the vectors it returns are
identical to calling OpenAI directly.

That gives two clean ways to satisfy requirement 5, both fully neocarta-aligned:

- **Option 1 — adopt neocarta's default OpenAI model (recommended for a true cutover).**
  - dbxcarta: create a Databricks External-Models endpoint backed by OpenAI
    `text-embedding-3-small`; set `DBXCARTA_EMBEDDING_ENDPOINT` to that endpoint and
    `DBXCARTA_EMBEDDING_DIMENSION=1536`.
  - MCP: leave `EMBEDDING_MODEL=text-embedding-3-small` and provide `OPENAI_API_KEY`
    (LiteLLM calls OpenAI directly). Same underlying model on both sides → same 1536-dim
    space.
- **Option 2 — keep the Databricks-native model.**
  - dbxcarta: keep `databricks-gte-large-en` (1024).
  - MCP: set `EMBEDDING_MODEL=databricks/databricks-gte-large-en` with Databricks auth
    (`DATABRICKS_API_BASE` / `DATABRICKS_API_KEY`) so LiteLLM embeds the query with the
    same model. Same 1024-dim space.

Either works. Option 1 matches the neocarta default end to end, so it is the cleaner
cutover; Option 2 avoids standing up an external endpoint and keeps embeddings inside
Databricks.

Notes:
- OpenAI v3 embedding models accept a `dimensions` parameter to shorten the vector; if
  used, both the stored vectors and the query vectors must request the same value, and
  the Neo4j vector index dimension must match it.
- Verify the exact endpoint/model wiring in the target Databricks workspace before
  relying on it.

---

## Provisioning the OpenAI Endpoint (Option 1, concrete steps)

Option 1 needs three things in order: the OpenAI key stored as a Databricks secret, an
External-Models serving endpoint that proxies it, and the dbxcarta config pointed at
that endpoint.

Steps A through C are scripted. `setup_secrets.sh` does Step A and
`scripts/setup-openai-endpoint.py` does Steps B and C. See the "Scripts" section below
for flags and behavior. The steps below describe what those scripts do and the manual
commands behind them.

### Step A. Store the OpenAI key as a Databricks secret

`setup_secrets.sh` provisions it from the gitignored standalone `.env`, so the key
value never passes through any other tool. The committed overlay names the scope; the
standalone `.env` holds the value.

- `examples/finance-genie/dbxcarta-overlay.env` sets `OPENAI_SECRET_SCOPE=dbxcarta-openai`.
- `examples/finance-genie/.env` sets `OPENAI_API_KEY=sk-...`.
- Run:

```bash
cd dbxcarta && ./setup_secrets.sh --profile aws-partner-rk --example finance-genie
```

The run reports both `scope: dbxcarta-neo4j-finance-genie` and
`openai scope: dbxcarta-openai (shared, from overlay)`. The endpoint below references
this secret as `{{secrets/dbxcarta-openai/OPENAI_API_KEY}}`.

### Step B. Create the External-Models embedding endpoint

The Databricks MCP server cannot create serving endpoints. Its `manage_serving_endpoint`
action is get/list/query only, so use the Databricks CLI. Save this as
`openai-embeddings-endpoint.json`:

```json
{
  "name": "openai-text-embedding-3-small",
  "config": {
    "served_entities": [
      {
        "name": "openai-text-embedding-3-small",
        "external_model": {
          "name": "text-embedding-3-small",
          "provider": "openai",
          "task": "llm/v1/embeddings",
          "openai_config": {
            "openai_api_key": "{{secrets/dbxcarta-openai/OPENAI_API_KEY}}"
          }
        }
      }
    ]
  }
}
```

Create it:

```bash
databricks serving-endpoints create --profile aws-partner-rk \
  --json @openai-embeddings-endpoint.json
```

Field rules, verified against the Databricks external-models tutorial:
- `task` is `llm/v1/embeddings`. This is what makes the endpoint an embeddings endpoint.
- `external_model.name` is the OpenAI model id `text-embedding-3-small`. The endpoint
  name `openai-text-embedding-3-small` is what dbxcarta and the MCP call.
- `openai_config.openai_api_key` takes a secret reference `{{secrets/<scope>/<key>}}`.
  The plaintext alternative `openai_api_key_plaintext` exists but exposes the key, so
  do not use it.
- External-models endpoints route to OpenAI, so no `workload_size` or `scale_to_zero`
  is needed.

### Step C. Verify before re-ingesting

Confirm the endpoint is live and returns 1536-dim vectors. The dimension probe runs
through the MCP `execute_sql` tool or the SQL CLI:

```bash
databricks serving-endpoints get --profile aws-partner-rk \
  --name openai-text-embedding-3-small
```

```sql
SELECT size(ai_query('openai-text-embedding-3-small',
  'gold_fraud_ring_communities: accounts grouped into detected fraud rings')) AS dim;
```

A result of `1536` confirms the stored-vector side. text-embedding-3-small is natively
1536-dim and dbxcarta sends no `dimensions` shrink parameter, so the endpoint dimension
equals the configured value.

### Step D. Point dbxcarta at the endpoint

The finance-genie overlay (`examples/finance-genie/dbxcarta-overlay.env`) already sets:

```
DBXCARTA_EMBEDDING_ENDPOINT=openai-text-embedding-3-small
DBXCARTA_EMBEDDING_DIMENSION=1536
```

These override the base `.env` defaults of `databricks-gte-large-en` / 1024. The MCP
read side already defaults to `text-embedding-3-small`, so it needs only `OPENAI_API_KEY`
in its own process env for LiteLLM at query time. After this, re-ingest (Phase 4) so the
graph is rebuilt with 1536-dim vectors from the new model.

---

## Scripts

Two scripts automate the secret and endpoint setup for the cutover.

### `setup_secrets.sh` (repo root): provision Databricks secrets

Reads each example's committed overlay for the scope NAMES and the gitignored standalone
`.env` for the secret VALUES, then creates the scopes and writes the secrets. The OpenAI
key never leaves your machine through any other tool.

Per example it provisions:
- the Neo4j scope named by `DATABRICKS_SECRET_SCOPE`, with `NEO4J_URI` / `NEO4J_USERNAME` / `NEO4J_PASSWORD`.
- the shared OpenAI scope named by `OPENAI_SECRET_SCOPE` when set, with `OPENAI_API_KEY`.

```bash
cd dbxcarta
./setup_secrets.sh --profile aws-partner-rk --example finance-genie
```

Flags: `--profile NAME` overrides the example's `DATABRICKS_PROFILE`; `--example NAME` is
repeatable and limits the run to the named examples. OpenAI provisioning is skipped when
the overlay names no `OPENAI_SECRET_SCOPE` or the `.env` has no `OPENAI_API_KEY`, so
existing integrations are unaffected.

### `scripts/setup-openai-endpoint.py`: create and verify the endpoint (Steps B and C)

Creates the OpenAI external-models embedding endpoint, then verifies it. It refuses to
run when the secret is missing and points back at `setup_secrets.sh`. It is idempotent:
when the endpoint already exists it skips creation and only re-verifies.

What it does:
1. checks the secret exists in the scope (guard).
2. creates the endpoint with provider `openai`, task `llm/v1/embeddings`, model
   `text-embedding-3-small`, and waits for `READY`.
3. runs `SELECT size(ai_query('<endpoint>', '<sample>'))` and asserts the result equals
   the expected dimension, which is `1536`.

```bash
uv run scripts/setup-openai-endpoint.py --profile aws-partner-rk \
  --warehouse-id <warehouse-id>
```

Defaults match the finance-genie overlay: endpoint `openai-text-embedding-3-small`,
model `text-embedding-3-small`, scope `dbxcarta-openai`, key `OPENAI_API_KEY`, dimension
`1536`. Flags: `--endpoint-name`, `--model`, `--secret-scope`, `--secret-key`,
`--dimension`, `--warehouse-id` for the probe, which falls back to `--env-file` then repo
`.env` then the first warehouse, `--env-file`, `--probe-text`, `--skip-verify` to create
only, and `-y` / `--yes` to skip the create confirmation prompt. Without `--yes` it prompts
before creating, so a non-interactive run that would create a new endpoint aborts safely.

Order of operations: run `setup_secrets.sh` first (Step A), then
`setup-openai-endpoint.py` (Steps B and C), then re-ingest (Phase 4).

---

## Phased Implementation

### Phase 1 — Change dbxcarta index creation
- Edit `bootstrap_constraints` in `dbxcarta-spark/.../ingest/load/neo4j_io.py`:
  - Rename vector index suffix `_embedding` → `_vector_index`.
  - Drop `Value` from the vector-index set.
  - Add the two full-text indexes (`table_full_text_index`, `column_full_text_index`).
  - Add the four name range indexes (`database_name_index` … `column_name_index`).

### Phase 2 — Write the version node
- Add a step that upserts the `__neocarta_graph__` node, mirroring neocarta's
  `upsert_neocarta_graph_node`, recording the neocarta version the MCP server runs.

### Phase 3 — Align embeddings
- Pick Option 1 or Option 2 above.
- For Option 1, follow "Provisioning the OpenAI Endpoint" above: store the key with
  `setup_secrets.sh`, create the External-Models endpoint, verify 1536 dims, then set
  the overlay config.
- Set `DBXCARTA_EMBEDDING_ENDPOINT` and `DBXCARTA_EMBEDDING_DIMENSION` accordingly, and
  confirm the vector index dimension matches.

### Phase 4 — Re-ingest
- Run a fresh dbxcarta ingest so the graph is rebuilt with the new index names, the new
  embedding model/dimension, and the version node. Re-embedding is required whenever the
  embedding model changes (the old 1024-dim vectors are not comparable to new 1536-dim
  vectors).

### Phase 5 — Point the MCP server at it and test
- Configure and launch `neocarta-mcp` (see test section) and confirm the tools work.

---

## How to Run an Initial Basic Test of the Flow

After re-ingesting (Phase 4) with the new contract, point the MCP server at that graph.

**Step 1 — configure the MCP server** (same Neo4j the dbxcarta job wrote to; embedding
model matching whatever dbxcarta used):

```
NEO4J_URI=neo4j+s://<the-finance-genie-instance>
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<password>
NEO4J_DATABASE=neo4j
# Option 1 (OpenAI default):
EMBEDDING_MODEL=text-embedding-3-small
OPENAI_API_KEY=<key>
# Option 2 (Databricks-native) instead:
# EMBEDDING_MODEL=databricks/databricks-gte-large-en
# DATABRICKS_API_BASE=https://<workspace>/serving-endpoints
# DATABRICKS_API_KEY=<token>
```

**Step 2 — start the server:** run the `neocarta-mcp` console script. On startup it logs
the detected index inventory; confirm it lists vector indexes for `Table` and `Column`
(and full-text if created), and that the version check logs a match rather than the
"no `__neocarta_graph__`" warning.

**Step 3 — exercise the tools** (catalog tools need no embeddings; the vector search is
the real end-to-end signal):

- `list_schemas` → returns the finance schema (`graph-enriched-schema`).
- `list_tables_by_schema` → lists `accounts`, `transactions`, `gold_accounts`,
  `gold_fraud_ring_communities`, etc.
- `get_full_metadata_schema` for one table → returns its columns with types.
- `get_context_by_table_vector_search` with *"which accounts are part of a fraud ring?"*
  → should rank `gold_accounts` / `gold_fraud_ring_communities` near the top. This only
  works if the stored vectors and the query vector are the same model and dimension.

**Step 4 — (optional) drive it as a real MCP client:** register the server in an
`.mcp.json` so Claude Code connects to it, and ask a natural-language question that
forces a tool call, confirming the full agent → MCP → Neo4j → answer path.

### What "passing" looks like
- Server starts, logs vector indexes for `Table` and `Column`, and a version match.
- Catalog tools return the finance schema and tables.
- A vector-search tool returns the obviously relevant finance tables for a plain-English
  question, with no dimension-mismatch error.

---

## Risks and Open Questions

- **Re-embedding cost**: changing the embedding model (Option 1) means re-embedding the
  whole graph; the old vectors cannot be reused. Plan the ingest accordingly.
- **External endpoint wiring**: if using Option 1, confirm the Databricks External-Models
  endpoint for `text-embedding-3-small` is provisioned and that dbxcarta can call it.
- **Dimension consistency**: the embedding dimension, the `dimensions` param (if any),
  and the Neo4j vector index dimension must all agree on both sides. A mismatch surfaces
  as a Neo4j vector-query error.
- **Schema vector tool**: `schema_vector_index` only exists if schema embeddings are
  enabled (`DBXCARTA_INCLUDE_EMBEDDINGS_SCHEMAS=true`, which finance-genie sets).
- **Version string source**: decide where dbxcarta reads the neocarta version to stamp on
  the `__neocarta_graph__` node, so it tracks the MCP server's `neocarta.__version__`.
