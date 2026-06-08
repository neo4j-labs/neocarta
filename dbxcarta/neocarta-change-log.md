# Neocarta Change Log: Adding dbxcarta

## Summary

This branch adds dbxcarta, the Databricks version of neocarta, into the neocarta repository. dbxcarta builds the same kind of Neo4j semantic layer that neocarta builds, but it reads from Databricks Unity Catalog using a Spark job instead of from neocarta's existing connectors. The work came in two parts. First, the whole dbxcarta capability was dropped in as a plain folder under `dbxcarta/`. Second, the parent neocarta project was changed in a handful of places so the two fit together as one workspace, share one set of tooling, and produce the same graph shape.

The changes break down into three groups: wiring dbxcarta into the build and packaging, wiring it into the tooling and tests, and aligning the graph schema so a dbxcarta graph looks identical to a neocarta graph.

## What dbxcarta is

- **dbxcarta:** The Databricks counterpart to neocarta. It builds a Neo4j semantic layer over Databricks Unity Catalog so an AI agent can traverse it.
- **Build time:** A single Databricks Spark job reads Unity Catalog metadata, embeds it with a Databricks foundation model, infers foreign keys, and writes typed nodes with vector properties into Neo4j.
- **Query time:** A client embeds a user question, runs a vector search to find the most relevant nodes, then walks the graph edges to expand that seed into a full schema subgraph for the LLM.
- **Five packages:** `dbxcarta-core` is the shared, Spark-free base. `dbxcarta-spark` is the build pipeline. `dbxcarta-submit` launches the job on Databricks. `dbxcarta-client` queries the finished graph and runs the Text2SQL evaluation. `dbxcarta-materialize` creates the bundled example demo tables.

## Packaging changes (how it builds)

Every edit in this section is to neocarta's root `pyproject.toml`, which wires the dbxcarta packages in as workspace members. The dbxcarta side contributes only new files: each `dbxcarta-*` package ships its own `pyproject.toml` under `dbxcarta/`, which arrived with the dropped-in folder rather than as an edit to existing config.

**Changed in neocarta (root `pyproject.toml`):**

- **uv workspace:** `pyproject.toml` now declares a `[tool.uv.workspace]` with eight members, the five dbxcarta packages plus three example packages. This makes the whole repo one shared lock file and one virtual environment.
- **TLDR on the shared lock:** This is the right setup for packages developed together and is not a problem, with one catch: the single shared lock forces the whole repo to Python 3.12+, so base neocarta is no longer tested on 3.10 and 3.11 even though its wheel still claims to support them.
- **TLDR on being a workspace:** The repo is now one project made of several packages instead of one package. They all share a single environment and lock file, install together with one `uv sync`, and can import each other directly without publishing, which makes developing across them easier but ties them to the same set of dependency versions.
- **Workspace sources:** A `[tool.uv.sources]` block points every `dbxcarta-*` dependency at the local workspace copy instead of a published package, so they resolve from inside the repo.
- **New extras:** `neocarta[dbxcarta-core]` and `neocarta[dbxcarta-spark]` were added as optional extras, so a user can install just the light base or the full Spark builder.
- **New dependency group:** A `dbxcarta` dependency group installs every dbxcarta package, all three examples, and the test and type tooling. Heavy dependencies like pyspark and neo4j arrive only through this group, so a plain `uv sync` stays light.
- **Python version floor:** The dbxcarta extras require Python 3.12 or newer. The shared lock and dev/CI now resolve at 3.12 and up, while the published `neocarta` wheel still supports 3.10.

**Changed in dbxcarta:** the five `dbxcarta-*` packages each ship their own `pyproject.toml` under `dbxcarta/`. Those are new files from the dropped-in folder, referenced by the root workspace above, not edits to existing config.

## Tooling and test changes (how it runs)

Most of this is neocarta-side: edits to root files (`Makefile`, `pyproject.toml`, `CLAUDE.md`, CI workflow, `.mcp.json`, `.gitignore`) that reach into `dbxcarta/`. The dbxcarta side owns the per-directory configs those root files delegate to.

**Changed in neocarta (root files):**

- **CI matrix:** `.github/workflows/pr-main-tests.yml` dropped Python 3.10 and 3.11 from its test matrix, leaving 3.12 and 3.13, because the shared workspace lock only resolves at 3.12 and up.
- **Make targets:** The root `Makefile` gained `dbxcarta-test`, `dbxcarta-test-it`, `dbxcarta-test-slow`, `dbxcarta-test-wheel`, and `dbxcarta-typecheck` targets, plus an `e2e-%` pattern target. They all delegate into the directory with `make -C dbxcarta` so it runs from its own working directory against `dbxcarta/Makefile`.
- **Ruff linting (root half):** the root `pyproject.toml` keeps neocarta's lint target at Python 3.10 so neocarta's own rules keep firing. Its `[tool.ruff.lint.per-file-ignores]` relax docstring and PySpark-alias rules for dbxcarta source, examples, scripts, and tests without loosening neocarta's own enforcement.
- **mypy:** A strict `[tool.mypy]` config was added to the root `pyproject.toml`, with content carried over from dbxcarta's standalone setup. It is enforced only on the dbxcarta packages through the `dbxcarta-typecheck` target; neocarta's own packages opt in later.
- **Agent guidelines:** `CLAUDE.md` gained a section telling any agent to read `dbxcarta/CLAUDE.md` before touching anything under `dbxcarta/`, since that file carries the pipeline design rules.
- **MCP and ignores:** A `.mcp.json` was added wiring up a local Databricks MCP server, and `.gitignore` now ignores `.idea/`.

**Changed in dbxcarta (per-directory configs):**

- **Ruff linting (dbxcarta half):** a nested `dbxcarta/ruff.toml` bumps the lint target to 3.12 only for the dbxcarta directory, the counterpart to the root half above.
- **Make targets target:** `dbxcarta/Makefile` defines the per-directory test, lint, and typecheck targets that the root `Makefile` invokes via `make -C dbxcarta`.

## Schema alignment (so the graphs match)

This is the core fitting-in work. dbxcarta was the side that changed; neocarta's core model in `neocarta/data_model/rdbms/core.py` stayed as the target. Every dbxcarta run is a clean rebuild, so there was no old graph to migrate.

- **Goal:** A graph built by dbxcarta from Unity Catalog should look the same as a graph built by a neocarta connector. Same node labels, same property names, same relationship structure, so the neocarta agent, MCP tools, and retrieval pipelines work on a dbxcarta graph without special-casing.
- **Contract version:** The dbxcarta graph contract in `dbxcarta.spark.contract` was moved to version 1.7 to match neocarta core.
- **Renamed text property:** Node text on `Schema`, `Table`, and `Column` is now `description`, renamed from `comment`.
- **Renamed column properties:** The `Column` data type is now `type`, renamed from `data_type`, and its nullability flag is now `nullable`, renamed from `is_nullable`.
- **New Database properties:** `Database` nodes gained `platform`, the cloud tag stored upper-cased and null when unset, `service`, the constant `"DATABRICKS"`, and `description`, null today since the extract reads no catalog comment.
- **New key flags:** `Column` nodes gained `is_primary_key` and `is_foreign_key`, derived at extract time from the catalog's declared constraints through a native Spark aggregate. This matches neocarta's declared-only semantics, so inferred `REFERENCES` edges never set the flags.
- **Renamed edge columns:** The `REFERENCES` edge join columns are now `source_column_id` and `target_column_id`, renamed from `source_id` and `target_id`. The structural `HAS_*` edges are unchanged.
- **Kept dbxcarta's extras:** Alignment renamed and reshaped to match the core, but kept dbxcarta's extra signal as additive properties: the medallion `layer` on tables, foreign-key confidence scores, and structural identity columns.

## MCP cutover (so the neocarta MCP server reads a dbxcarta graph directly)

This is the read-side work. The neocarta MCP server now reads a dbxcarta graph with no compatibility layer. As with the schema alignment above, dbxcarta was the side that changed: the server already expected this index, version, and embedding contract, so nothing in neocarta's `_mcp` package changed for the cutover. dbxcarta's index names, full-text and range indexes, version node, and embedding model were cut over to match. The details and ELI5 live in `dbxcarta/mcp-v2.md`; this is the summary.

**Changed in dbxcarta:**

- **Vector indexes renamed:** from `<label>_embedding` to `<label>_vector_index` on `Table`, `Column`, `Schema`, and `Database`. `Value` dropped from the vector set; `Value` nodes still traverse via `HAS_VALUE`.
- **Full-text indexes added:** `table_full_text_index` and `column_full_text_index` over `name` plus `description`, so the server's full-text and hybrid tools register.
- **Name range indexes added:** `database_name_index`, `schema_name_index`, `table_name_index`, and `column_name_index` on `name`.
- **Version node upserted:** `__neocarta_graph__` is written on every ingest, mirroring neocarta's `upsert_neocarta_graph_node`, so the server's writer/reader version check logs a match instead of warning.
- **Embedding model aligned:** to OpenAI `text-embedding-3-small` at 1536 dims through a Databricks External-Models serving endpoint, so dbxcarta's stored vectors and the MCP server's query vectors share one embedding space and search resolves.
- **Where it lives:** `dbxcarta-spark/.../ingest/load/neo4j_io.py` (`bootstrap_constraints`, `upsert_neocarta_graph_node`), called from `dbxcarta-spark/.../run.py`; the embedding endpoint and dimension are set in `examples/finance-genie/dbxcarta-overlay.env`.

**Changed in neocarta:** nothing. The `_mcp` package was the unchanged target.

## MCP client/server separation (how it is tested)

The MCP client and server are now separate processes with separate responsibilities. The server owns its own Neo4j connection; the test client only connects by URL and probes tools. This work touched both sides: the server gained an HTTP transport in neocarta, and the test client and docs were rewritten in dbxcarta.

**Changed in neocarta:**

- **HTTP serve mode added:** the `neocarta-mcp` entry point (`neocarta/_mcp/server.py`) now serves over streamable HTTP with `neocarta-mcp --http [--host] [--port] [--path /mcp]`, in addition to the default stdio transport. This lets the server run independently so a client can reach it by URL. It uses FastMCP's documented `run_async(transport="http", ...)` surface, with host and port passed at the run call rather than the constructor.
- **Server self-configures (unchanged behavior, now relied upon):** it reads `NEO4J_*` and `OPENAI_API_KEY` from its own `.env` via `load_dotenv()` at startup, the same way it does in production. No credentials are forwarded from the client.

**Changed in dbxcarta:**

- **Test script is a pure client:** `scripts/test-neocarta-mcp.py` no longer launches the server or reads any Neo4j credentials. It requires `--url`, connects over streamable HTTP, lists every registered tool, and probes each one with a sensible argument. The registered tool set is discovered at runtime, so it reflects exactly which indexes the target database has.
- **Two-terminal workflow:** launch the server in one terminal (`uv run neocarta-mcp --http --port 8000`) and run the client against its URL in another (`uv run scripts/test-neocarta-mcp.py --url http://127.0.0.1:8000/mcp`).
- **Docs use `.env`, not manual exports:** `dbxcarta/mcp-v2.md` and the script's own usage now configure the server through a `.env` copied from the repo-root `.env.example`, rather than inline `VAR=... uv run` commands.
