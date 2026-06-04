# dbxcarta Dense Schema Example

This directory is a standalone integration example package,
`dbxcarta-dense-schema-example`. It generates a synthetic single-schema
Unity Catalog workload with hundreds of tables so dbxcarta retrieval can be
tested against dense schema context.

The package depends on `dbxcarta-spark` and `dbxcarta-client`. Its tests live
under `tests/examples/dense-schema/` and run in CI as a first-class sample
consumer.

## Quick Start

The full flow from a clean checkout to a scored client run. The first block is
one-time setup; the two make targets are the loop you repeat on every change.
The [Setup flow](#setup-flow) section explains each step in more detail.

```bash
# Install dbxcarta into the workspace virtualenv
uv sync
# Install this example package in editable mode
uv pip install -e examples/dense-schema/

# Copy the env template, then edit it for your profile and warehouse
cp examples/dense-schema/.env.sample examples/dense-schema/.env
# Create the ops plane and the dense-schema-example data catalog
uv run dbxcarta-submit bootstrap --env-file examples/dense-schema/dbxcarta-overlay.env
# Stage the committed dense_500 blueprint and run the serverless materialize job
uv run dbxcarta-submit materialize --env-file examples/dense-schema/dbxcarta-overlay.env

# Point every dbxcarta command at the dense-schema overlay
export DBXCARTA_ENV_FILE=examples/dense-schema/dbxcarta-overlay.env
# Confirm the dense_500 schema and its tables are materialized
uv run dbxcarta preset dbxcarta_dense_schema_example:preset --check-ready
# Upload the matching question set to the ops volume
uv run dbxcarta preset dbxcarta_dense_schema_example:preset --upload-questions
```

With setup in place, run the two make targets from the repo root. The `-ingest`
target rebuilds the wheels from current source and builds the semantic layer, so
run it first and let it finish, then run `-client`:

```bash
# Rebuild the wheels from source, submit ingest, build the semantic layer
make e2e-dense-schema-ingest
# Submit the client evaluation once ingest finishes
make e2e-dense-schema-client
```

## What lives here

```text
examples/dense-schema/
├── pyproject.toml
├── .env.sample
├── filter_questions.py
├── questions.json
├── blueprint/                  # committed candidate JSON (dense_500)
└── src/dbxcarta_dense_schema_example/
    ├── generator.py
    ├── preset.py
    └── question_generator.py
```

## Quick iterate loop (testing dbxcarta changes)

Once the one-time setup is in place (example installed, the ops plane and data
catalog bootstrapped, the committed blueprint materialized into the data
catalog, and the question set uploaded), the wheel-rebuild-and-submit pipeline
runs in two make targets from the repo root — ingest first, then the client
evaluation once ingest finishes:

```bash
# Rebuild the wheels from source, submit ingest, build the semantic layer
make e2e-dense-schema-ingest
# Submit the client evaluation once ingest finishes
make e2e-dense-schema-client
```

The `-ingest` target rebuilds the wheels from your current source, then
submits `ingest`; the `-client` target submits `client`, so it reflects
local edits to the dbxcarta packages on every run. The targets set
`DBXCARTA_ENV_FILE` to this directory's committed `dbxcarta-overlay.env`
inline on each command, so they pick up the right dbxcarta config from any
shell. `make help` lists the targets for every example.

## Setup flow

Run these commands from the dbxcarta repo unless a step says otherwise.

```bash
# Install dbxcarta into the workspace virtualenv
uv sync
# Install this example package in editable mode
uv pip install -e examples/dense-schema/
```

The Blueprint stage is already done: the committed
`blueprint/candidates_500.json` (schema `dense_500`, 500 tables) is the source of
truth, so no generation step is required for a normal run. To regenerate it,
write a fresh blueprint and commit it over the existing file:

```bash
# Regenerate the dense_500 blueprint and write it over the committed file
uv run dbxcarta-dense-generate --tables 500 \
  --output examples/dense-schema/blueprint/candidates_500.json
```

Provision the ops plane, the `dbxcarta-catalog.dense-ops` schema and its
`dbxcarta-ops` volume named by the overlay's `DATABRICKS_VOLUME_PATH`, after
configuring `.env`. `bootstrap` also creates the `dense-schema-example` data
catalog from the overlay's `DBXCARTA_CATALOG`. It is idempotent, so re-running it
changes nothing; the `-ingest` make target also runs it first:

```bash
# Provision the ops plane and create the dense-schema-example data catalog
uv run dbxcarta-submit bootstrap --env-file examples/dense-schema/dbxcarta-overlay.env
```

Materialize the committed blueprint into Unity Catalog. Materialize is a shared
product step, the same serverless Spark entrypoint every example uses, configured
through the overlay. The command stages `blueprint/candidates_500.json` to the ops
Volume, then submits the `dbxcarta-materialize` job, which creates the `dense_500`
schema and its tables in the data catalog that bootstrap already created:

```bash
# Stage the blueprint to the volume and run the serverless materialize job
uv run dbxcarta-submit materialize --env-file examples/dense-schema/dbxcarta-overlay.env
```

To remove dense's full footprint later, run `teardown`. It drops the overlay's
`DBXCARTA_TEARDOWN_TARGET`,
`catalog:dense-schema-example,schema:dbxcarta-catalog.dense-ops`: the data
catalog and dense's ops schema. The shared `dbxcarta-catalog` is left intact for
the other examples:

```bash
# Drop the data catalog and dense's ops schema, leaving the shared catalog intact
uv run dbxcarta-submit teardown --env-file examples/dense-schema/dbxcarta-overlay.env --yes-i-mean-it
```

Then use the preset with the normal dbxcarta operational CLI:

```bash
# Confirm the dense_500 schema and its tables are materialized
uv run dbxcarta preset dbxcarta_dense_schema_example:preset --check-ready
# Upload the question set to the ops volume
uv run dbxcarta preset dbxcarta_dense_schema_example:preset --upload-questions
# Submit the ingest job to build the semantic layer
uv run dbxcarta-submit submit-entrypoint ingest
# Submit the client evaluation job
uv run dbxcarta-submit submit-entrypoint client
```

Synthetic blueprint generation and question generation stay inside this example.
They are not part of the `dbxcarta-spark` or `dbxcarta-client` public APIs.
Materialize is the shared product step, run as the `dbxcarta-materialize` job.
