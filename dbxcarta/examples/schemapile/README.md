# dbxcarta SchemaPile Example

This directory is a standalone Python package, `dbxcarta-schemapile-example`,
that materializes a slice of [SchemaPile](https://github.com/amsterdata/schemapile)
as Delta tables in a dedicated Unity Catalog catalog and runs dbxcarta
against the result. It is a second reference consumer alongside the
finance-genie example and shares no state with it.

The package depends on `dbxcarta-spark` and `dbxcarta-client`. Its tests live
under `tests/examples/schemapile/` so the repo-level CI can run it as a
first-class integration consumer.

## Quick Start

The full flow from a clean checkout to a scored client run. The first block is
one-time setup; the two make targets are the loop you repeat on every change.
Each numbered section under [Setup flow](#setup-flow) explains a step in more
detail. Fetch the upstream `schemapile-perm.json` artifact first; see
[section 2](#2-get-the-upstream-schemapile-data).

```bash
# Install dbxcarta and this example
uv sync
uv pip install -e examples/schemapile/

# Build the slice through to a question set. These steps read
# examples/schemapile/.env, so run them from that directory.
cd examples/schemapile
cp .env.sample .env                             # edit SCHEMAPILE_REPO, profile, warehouse, catalog
uv run dbxcarta-submit bootstrap --env-file dbxcarta-overlay.env     # ops catalog + volume + data catalog
# Run the upstream slice.py with the .env parameters; writes the cached slice JSON (idempotent on its params sidecar).
uv run dbxcarta-schemapile-slice
# Filter, rank, and cap the slice into the committed candidate-table JSON read by materialize and question generation.
uv run dbxcarta-schemapile-select
uv run dbxcarta-submit materialize --env-file dbxcarta-overlay.env   # stage blueprint, run serverless job
uv run dbxcarta-schemapile-generate-questions
cd ../..

# Select the SchemaPile overlay for every command below. No schema list to
# copy: schemapile_lakehouse is a dedicated, data-only catalog, so the ingest
# auto-discovers the materialized schemas from a blank DBXCARTA_SCHEMAS.
export DBXCARTA_ENV_FILE=examples/schemapile/dbxcarta-overlay.env

# Confirm the schemas materialized, then upload the generated question set.
uv run dbxcarta preset dbxcarta_schemapile_example:preset --check-ready
uv run dbxcarta preset dbxcarta_schemapile_example:preset --upload-questions
```

With setup in place, run the two make targets from the repo root. The `-ingest`
target rebuilds the wheels from current source and builds the semantic layer, so
run it first and let it finish, then run `-client`:

```bash
make e2e-schemapile-ingest
make e2e-schemapile-client
```

## What lives here

```
examples/schemapile/
├── pyproject.toml
├── README.md
├── .env.sample
├── src/dbxcarta_schemapile_example/
│   ├── __init__.py
│   ├── preset.py                # module-level `preset` (shared StandardPreset)
│   ├── config.py                # one-shot .env parser
│   ├── slice_runner.py          # shells out to upstream slice.py
│   ├── candidate_selector.py    # slice JSON -> candidate-table JSON (blueprint)
│   └── question_generator.py    # LLM + SQL validation -> questions.json
├── blueprint/                   # committed candidate JSON + attribution
├── scripts/                     # one-off utilities, see scripts/README.md
│   └── dump_question_context.py # Neo4j -> docs/schemapile/questions-schema.md
└── ../../../tests/examples/schemapile/
```

## Quality caveat for the generated question set

The evaluation `questions.json` is produced by prompting a foundation model
with each candidate schema's DDL, asking for question and SQL pairs, then
executing each candidate SQL against the materialized tables and keeping
only the pairs that run cleanly, return at least one row, and do not return
a single trivial scalar.

This is useful for *relative comparison* across the three dbxcarta arms
(`no_context`, `schema_dump`, `graph_rag`). It is not a hand-curated gold
benchmark and should not be cited as evidence of absolute correctness.

## Quick iterate loop (testing dbxcarta changes)

Once the one-time setup is in place (steps 1–8 below: example installed,
catalog bootstrapped, slice/candidates/Delta tables materialized, and the
question set uploaded), the wheel-rebuild-and-submit half of step 9 runs
in two make targets from the repo root. Run ingest first, then the client
evaluation once ingest finishes:

```bash
make e2e-schemapile-ingest
make e2e-schemapile-client
```

The `-ingest` target rebuilds the wheels from your current source, then
submits `ingest`; the `-client` target submits `client`, so it reflects
local edits to the dbxcarta packages on every run. The targets set
`DBXCARTA_ENV_FILE` to this directory's
`dbxcarta-overlay.env` inline on each command, so they pick up the right
dbxcarta config from any shell. They do not use this directory's
standalone `./.env`, which configures the host-only slice, select, and
question-generation tooling only.
`make help` lists the targets for every example.

## Setup flow

Run from the dbxcarta repo unless a step says otherwise.

### 1. Install dbxcarta and the example

```bash
uv sync
uv pip install -e examples/schemapile/
```

### 2. Get the upstream SchemaPile data

The example never downloads `schemapile-perm.json` itself. Clone the
upstream repo and follow its README to fetch the 286 MB JSON artifact:

```bash
git clone https://github.com/amsterdata/schemapile.git ~/projects/schemapile
# Follow upstream instructions to download schemapile-perm.json into that dir.
```

### 3. Configure the example .env

```bash
cd examples/schemapile
cp .env.sample .env
# Edit .env and fill in:
#   SCHEMAPILE_REPO=~/projects/schemapile
#   DATABRICKS_PROFILE=<your profile>
#   DATABRICKS_WAREHOUSE_ID=<your warehouse id>
#   DBXCARTA_CATALOG=schemapile_lakehouse  (or your override)
```

The example refuses to run if `DBXCARTA_CATALOG` matches a known project
catalog (e.g. `graph-enriched-lakehouse`).

### 4. Bootstrap the ops plane (catalog + volume)

Requires catalog-create privilege on the workspace.

```bash
cd examples/schemapile
uv run dbxcarta-submit bootstrap --env-file dbxcarta-overlay.env
```

This provisions the **ops plane** named by the overlay's
`DATABRICKS_VOLUME_PATH`: the `dbxcarta-catalog` catalog, the
`schemapile_ops` schema, and the `dbxcarta-ops` volume that hold wheels,
run summaries, and the question set. It also creates the **data** catalog
the overlay names in `DBXCARTA_CATALOG` (`schemapile_lakehouse`). The
materialize step (section 7) assumes that catalog already exists. It is
idempotent.

To tear down later, `teardown` drops both targets the overlay names in
`DBXCARTA_TEARDOWN_TARGET`: the data catalog `schemapile_lakehouse` and
the ops schema `dbxcarta-catalog.schemapile_ops`. The shared
`dbxcarta-catalog` itself is left intact for other examples.

```bash
uv run dbxcarta-submit teardown --env-file dbxcarta-overlay.env --yes-i-mean-it
```

### 5. Produce the SchemaPile slice (host-only, no credentials needed)

```bash
uv run dbxcarta-schemapile-slice
```

Shells out to the upstream `slice.py` with the parameters from `.env`,
writes the JSON to `SCHEMAPILE_SLICE_CACHE`, and records a sidecar params
file so subsequent runs with the same parameters are a no-op.

### 6. Pick the candidate set (host-only)

```bash
uv run dbxcarta-schemapile-select
```

Reads the slice JSON, applies the candidate filters, and writes a fixed
candidate-table JSON to `SCHEMAPILE_CANDIDATE_CACHE`, which resolves to the
committed `blueprint/candidates_random_1000.json`. This file is the committed
source of truth for the next two steps; re-running select regenerates it in
place, so commit the result for a fully reproducible run.

### 7. Materialize the slice as Delta tables

```bash
uv run dbxcarta-submit materialize --env-file dbxcarta-overlay.env
```

Materialize is a shared product step, the same serverless Spark
entrypoint every example uses, configured through the overlay rather than
a per-example script. The command stages the committed blueprint (the
single `*.json` under `blueprint/`, which `dbxcarta-schemapile-select`
regenerates in place) to the ops Volume, then submits the
`dbxcarta-materialize` job. The job creates one UC schema per candidate
(`sp_<sanitized_id>`) and one Delta table per table spec in the
`schemapile_lakehouse` data catalog that bootstrap already created. Types
are coerced to Delta with a documented map; anything unrecognized falls
back to `STRING`. When the blueprint carries row-aligned sample VALUES for
a table, the job loads them with a single `INSERT OVERWRITE` so re-runs are
idempotent; tables without sample VALUES land typed-but-empty. The
original source filename, primary key list, and foreign key list are
recorded as Delta table properties on every table so the trace from a UC
table to its schemapile origin is always one query away.

No schema list is emitted. `schemapile_lakehouse` is a dedicated,
data-only catalog, so the dbxcarta run auto-discovers every materialized
schema from a blank `DBXCARTA_SCHEMAS` in the overlay.

### 8. Generate and validate the question set

```bash
uv run dbxcarta-schemapile-generate-questions
```

Two stages. The first stage prompts `SCHEMAPILE_QUESTION_MODEL` with each
candidate schema's DDL and asks for the configured number of question
and SQL pairs split across single-table filter, two-table join, and
aggregation. The second stage executes each candidate SQL against the
materialized tables on the configured SQL warehouse and keeps only the
pairs that run cleanly, return at least one row, and do not return a
single trivial scalar. Pairs that survive both stages are written to
`questions.json`. The LLM output is cached per (uc_schema, model, seed,
temperature) so a re-run with the same parameters does not re-bill the
model.

### 9. Run dbxcarta against the schemapile catalog

dbxcarta loads config in two layers: the repo-root `.env` is the shared
base, holding Databricks infra and Neo4j secrets, never edited per
integration. This directory's committed, secret-free
`dbxcarta-overlay.env` is the SchemaPile overlay, holding dbxcarta-scoped
values only. Selecting it is one variable, no root `.env` edit. There is
no schema list to copy: `DBXCARTA_SCHEMAS` ships blank because
`schemapile_lakehouse` is data-only and auto-discovered. Export
`DBXCARTA_ENV_FILE` once and run the standard flow from the repo root.
The `dbxcarta-submit` subcommands read the overlay from the environment
and do not accept a `--env-file` flag, so the export is the mechanism
that selects it:

```bash
# Select the SchemaPile overlay once for every command below.
export DBXCARTA_ENV_FILE=examples/schemapile/dbxcarta-overlay.env

# Confirm the preset resolves and the upstream schemas are materialized.
uv run dbxcarta preset dbxcarta_schemapile_example:preset --check-ready

# Upload the generated question set to the example volume.
uv run dbxcarta preset dbxcarta_schemapile_example:preset --upload-questions

# Build and submit the ingest job. publish-wheels rebuilds the wheels and
# ships the bootstrap script (it calls upload_all internally), so no
# separate `upload --all` step is needed.
uv run dbxcarta-submit publish-wheels
uv run dbxcarta-submit submit-entrypoint ingest
uv run dbxcarta verify

# Run the client evaluation arms.
uv run dbxcarta-submit submit-entrypoint client
```

For the wheel-rebuild-and-submit half of this step on every code change,
`make e2e-schemapile-ingest` then `make e2e-schemapile-client` from the
repo root is the shortcut (see the Quick iterate loop section above).

This overlay is the dbxcarta CLI overlay only. It is distinct from
`./.env` / `./.env.sample`, which configure the standalone SchemaPile
tooling (slice/candidate/question generation) and never layer. The shared
materialize job reads the overlay, not this `./.env`.

## Supporting scripts

One-off utilities live in `scripts/`. See `scripts/README.md` for the
full list. The current entry:

- `dump_question_context.py` — queries the live Neo4j graph and emits
  the three context blocks (schema dump, FK list, sample values) used
  while iterating on SchemaPile question generation. Regenerate
  `docs/schemapile/questions-schema.md` whenever the ingest graph changes.

## Phase dependencies and order

This example is built in phases that build on top of each other:

1. **Phase 0 (dbxcarta core)**. Multi-schema `DBXCARTA_SCHEMAS` is supported
   end to end; FK inference is restricted to within-schema pairs.
2. **Phase 1 (questions)**. The candidate JSON is the single source of
   truth shared with the materializer and the question generator.
3. **Phase 2 (slice runner)**. Host-only; depends only on the upstream
   schemapile checkout.
4. **Phase 3 (bootstrap)**. Provisions the catalog and volume.
5. **Phase 4 (materialize)**. The shared serverless `dbxcarta-materialize`
   job, configured per example through the overlay: stages the committed
   blueprint and writes Delta tables.
6. **Phase 5 (package wiring)**. This package; exposes the preset.
7. **Phase 6 (end-to-end run)**. Runs the assembled example against a live
   workspace and compares evaluation arms.

This README is now the source of truth for the SchemaPile example flow.
