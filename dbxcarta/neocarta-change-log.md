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

- **uv workspace:** `pyproject.toml` now declares a `[tool.uv.workspace]` with eight members, the five dbxcarta packages plus three example packages. This makes the whole repo one shared lock file and one virtual environment.
- **TLDR on the shared lock:** This is the right setup for packages developed together and is not a problem, with one catch: the single shared lock forces the whole repo to Python 3.12+, so base neocarta is no longer tested on 3.10 and 3.11 even though its wheel still claims to support them.
- **TLDR on being a workspace:** The repo is now one project made of several packages instead of one package. They all share a single environment and lock file, install together with one `uv sync`, and can import each other directly without publishing, which makes developing across them easier but ties them to the same set of dependency versions.
- **Workspace sources:** A `[tool.uv.sources]` block points every `dbxcarta-*` dependency at the local workspace copy instead of a published package, so they resolve from inside the repo.
- **New extras:** `neocarta[dbxcarta-core]` and `neocarta[dbxcarta-spark]` were added as optional extras, so a user can install just the light base or the full Spark builder.
- **New dependency group:** A `dbxcarta` dependency group installs every dbxcarta package, all three examples, and the test and type tooling. Heavy dependencies like pyspark and neo4j arrive only through this group, so a plain `uv sync` stays light.
- **Python version floor:** The dbxcarta extras require Python 3.12 or newer. The shared lock and dev/CI now resolve at 3.12 and up, while the published `neocarta` wheel still supports 3.10.

## Tooling and test changes (how it runs)

- **CI matrix:** `.github/workflows/pr-main-tests.yml` dropped Python 3.10 and 3.11 from its test matrix, leaving 3.12 and 3.13, because the shared workspace lock only resolves at 3.12 and up.
- **Make targets:** The root `Makefile` gained `dbxcarta-test`, `dbxcarta-test-it`, `dbxcarta-test-slow`, `dbxcarta-test-wheel`, and `dbxcarta-typecheck` targets, plus an `e2e-%` pattern target. They all delegate into the directory with `make -C dbxcarta` so it runs from its own working directory.
- **Ruff linting:** `pyproject.toml` keeps neocarta's lint target at Python 3.10 so neocarta's own rules keep firing, while a nested `dbxcarta/ruff.toml` bumps the target to 3.12 only for the dbxcarta directory. Per-path ignores relax docstring and PySpark-alias rules for dbxcarta source, examples, scripts, and tests without loosening neocarta's own enforcement.
- **mypy:** A strict `[tool.mypy]` config was added, carried over from dbxcarta. It is enforced only on the dbxcarta packages through the `dbxcarta-typecheck` target; neocarta's own packages opt in later.
- **Agent guidelines:** `claude.md` gained a section telling any agent to read `dbxcarta/CLAUDE.md` before touching anything under `dbxcarta/`, since that file carries the pipeline design rules.
- **MCP and ignores:** A `.mcp.json` was added wiring up a local Databricks MCP server, and `.gitignore` now ignores `.idea/`.

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
