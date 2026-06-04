# DBxCarta — CLAUDE.md

## Critical design rules

Before writing or changing Spark code, read `docs/reference/best-practices.md`. In particular:

- **Never use a Python UDF or `pandas_udf` for rule logic in the Spark pipeline.** Catalyst cannot optimize a UDF: it blocks predicate pushdown and whole-stage codegen and pays Arrow serialization per batch, which dominates large or n²-shaped joins. Logic driven by small static tables (suffix lists, type-class maps, score tables, stopwords) must be expanded into native `Column` expressions and broadcast-join lookups at plan-construction time. Python builds the plan; Spark evaluates every row. See `docs/reference/best-practices.md` §7 (Spark / Databricks).
- **Never collect catalog-scale data to the driver.** Keep columns, constraints, values, and FK candidates in DataFrames. See `docs/reference/best-practices.md` §5.

`docs/reference/best-practices.md` is the authoritative list of pipeline design rules with sources. Add to it (with a cited source) when a rule is established; do not let these rules regress.

## Environment configuration (layered)

dbxcarta loads env config in two layers. See `docs/proposals/env-layering.md`.

- The repo-root `.env` is the shared **base**: Databricks infra (profile, compute, workspace, warehouse), shared chat/embedding endpoints, and the base Neo4j secrets. It is gitignored and **never edited per integration**. It does **not** set `DATABRICKS_SECRET_SCOPE` (that is per-integration, see below).
- Each integration ships a committed, secret-free `examples/<name>/dbxcarta-overlay.env`. This is the **single source of truth** for that integration's per-example dbxcarta config: catalog/catalogs/layer-map/schemas, volume, summary, sample/embedding flags, client arms, **and the per-integration `DATABRICKS_SECRET_SCOPE`** (a scope name, not a secret). Presets carry no env config — only optional behavior (readiness, question upload).
- Select an integration with one flag: `uv run dbxcarta <cmd> --env-file examples/<name>/dbxcarta-overlay.env`, or export `DBXCARTA_ENV_FILE` to that path. `--env-file` wins over `DBXCARTA_ENV_FILE`. The submit path forwards the overlay's `KEY=VALUE` pairs to the cluster as job parameters, so the overlay must stay secret-free.
- Precedence, lowest to highest: base `.env` → overlay → real exported process env. A selected overlay that does not resolve is a hard error, never a silent base-only fallback. `databricks_secret_scope` has no code default, so a run with no overlay fails loudly at config load.
- Do not put `NEO4J_*` or any secret in an overlay (overlays are committed and shipped as job params). Do not write integration-scoped values back into the root `.env`.
- The `examples/<name>/.env` and `.env.sample` files are the **separate** self-contained config for that integration's standalone tooling (local demo, slice/materialize) and hold the per-integration `NEO4J_*` secrets. `setup_secrets.sh` reads the scope name from the overlay and the `NEO4J_*` values from this `.env` to provision the Databricks secret scope. These files never layer and are not the dbxcarta CLI overlay.
