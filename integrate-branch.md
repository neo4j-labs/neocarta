# Integrating dbxcarta into neocarta

How the `dbxcarta/` workspace in this repo changes to adopt the integration
pattern established on the `add-databricks-connector-from-dbxcarta` branch.
The end state: the Spark ingest pipeline is a first-class neocarta connector,
the reusable parts of `dbxcarta-core` live inside the neocarta package,
neocarta publishes the Spark dependencies as an extra, and `dbxcarta/` remains
in the repo as a deployment and examples directory that shows how to run the
connector as Databricks jobs.

## What the branch already establishes

The branch (4 commits, latest `15608dc`) proves out the pattern. It is the
template for the migration, even where the local `dbxcarta/` tree has since
moved ahead of it.

**`dbxcarta-spark` becomes `neocarta/connectors/databricks/`.** The full ingest
pipeline moved into the neocarta package:

```
neocarta/connectors/databricks/
├── __init__.py          # exports DatabricksSparkSchemaConnector; Spark imports are lazy
├── connector.py         # DatabricksSparkSchemaConnector wrapper class
├── contract.py          # NodeLabel/RelType enums, property lists, CONTRACT_VERSION
├── settings.py          # SparkIngestSettings (env-driven, NEOCARTA_DATABRICKS_* vars)
├── run.py               # orchestrator: preflight → extract → values → write → FK → write
├── _platform/           # Databricks SDK helpers ported from dbxcarta-core
│   ├── catalogs.py      #   resolve_catalogs
│   └── identifiers.py   #   identifier validation, quoting, UC volume paths
└── ingest/
    ├── extract.py       # information_schema reads
    ├── schema_graph.py  # node/relationship DataFrame builders
    ├── contract_expr.py # Spark expressions matching Python id generation
    ├── preflight.py     # catalog/volume/Neo4j connectivity checks
    ├── summary.py       # RunSummary
    ├── fk/              # declared FK extraction + discovery orchestration
    ├── load/neo4j_io.py # constraints, stale-value cleanup, Spark Connector writes
    └── transform/       # sampled column values (value_stage, sample_values)
```

**Two architectural decisions in the port worth preserving:**

1. **The Spark job ingests catalog facts only.** The embed stage from
   `dbxcarta-spark` was deliberately dropped. Embeddings are added afterward by
   neocarta's existing enrichment layer rather than by Databricks serving
   endpoints inside the Spark job. This keeps one embedding path for all
   connectors.
2. **Heuristic FK inference moved to `neocarta/enrichment/foreign_keys/`**
   with `infer.py` and `rules.py`. Declared FK extraction stays in the
   connector because it is a catalog fact; inferred FKs are enrichment, shared
   conceptually with other sources. The connector ingests declared constraints
   only.

**Packaging on the branch:**

- `databricks-sdk>=0.40` joins the **base dependencies**. It is pure Python and
  small, and it backs the `_platform` helpers, so the connector class is
  importable in every install.
- A new extra carries the heavy dependency:

  ```toml
  [project.optional-dependencies]
  databricks-spark = [
      "pyspark>=3.5",
      "pydantic-settings>=2.12.0",
  ]
  ```

- A `databricks` dependency-group adds pytest for local no-cluster Spark tests,
  run via `uv run --group databricks` and a `test-databricks` Make target.
- Ruff per-path ignores scope the ported code's docstring and PySpark-idiom
  exemptions to `neocarta/connectors/databricks/**` and
  `neocarta/enrichment/foreign_keys/**`, keeping the repo-wide gate intact.
- Lazy imports throughout: `import neocarta.connectors.databricks` works
  without pyspark installed, and `connector.run()` raises a clear
  `ImportError` pointing at `pip install neocarta[databricks-spark]`.

**What the branch leaves unfinished** (it is WIP): `tests/unit/connectors/
databricks/` is referenced in ruff config but contains no tests, the leftover
`dbxcarta/dbxcarta-spark/pyproject.toml` still declares scripts pointing at
deleted modules, and the connector does not yet conform to neocarta's
`SourceConnectorProtocol`. These become work items below.

## Recommendation: where dbxcarta-core goes

`dbxcarta-core` should **dissolve along the seam the branch already cut**, not
relocate wholesale. Its modules split into two tiers:

### Tier 1: Databricks platform helpers → `neocarta/connectors/databricks/_platform/`

These are the modules every Databricks integration needs, and they depend only
on `databricks-sdk`, which is a base dependency. They become part of core
neocarta, importable without any extra:

| dbxcarta-core module | Destination | Why |
|---|---|---|
| `catalogs.py` | `_platform/catalogs.py` | already ported on the branch |
| `identifiers.py` | `_platform/identifiers.py` | already ported on the branch |
| `volume_io.py` | `_platform/volume_io.py` | preflight and summary I/O need UC Volume access |
| `workspace.py` | `_platform/workspace.py` | workspace metadata and secret-scope reads |
| `executor.py` | `_platform/executor.py` | SQL warehouse execution; future query-log connector and agent SQL execution will want it |
| `env.py` / `config.py` | fold into `settings.py` | neocarta already uses python-dotenv; the overlay-env mechanics belong to the settings boundary |

Keep `_platform` private for now. Nothing outside the Databricks connector
consumes these helpers today, so the connector package is the right home.
If a second Databricks integration appears later, for example a Databricks
query-history connector mirroring `connectors/bigquery/logs/`, promote
`_platform` to a shared `neocarta/connectors/databricks/platform/` public
module at that point. Do not create a top-level `neocarta/databricks/` package
speculatively.

### Tier 2: example and eval scaffolding → stays in `dbxcarta/`

`materialize.py`, `presets.py`, `questions.py`, and `sql_safety.py` exist to
seed demo tables, upload question sets, and guard generated SQL in the eval
harness. They are not part of the semantic-layer product and have no consumer
inside the neocarta package. They move into a small local support package
inside the `dbxcarta/` directory (see layout below) rather than into neocarta.
This matches the branch, which already slimmed `dbxcarta-core` down to exactly
these modules.

## Published packages and extras

neocarta stays a single published distribution. No separate dbxcarta packages
go to PyPI.

```toml
dependencies = [
    # ...existing...
    "databricks-sdk>=0.40",        # base: powers _platform, pure Python
]

[project.optional-dependencies]
databricks-spark = [               # run the Spark ingest connector
    "pyspark>=3.5",
    "pydantic-settings>=2.12.0",
]
```

Users install:

- `pip install neocarta` to import the connector class, settings, and contract.
- `pip install neocarta[databricks-spark]` to actually run the ingest, locally
  via Spark Connect or as a Databricks job.

Keep the extra named `databricks-spark`, as the branch does, rather than
`dbxcarta-spark`. Extras should name the platform and execution model, not the
legacy project. The Databricks job itself installs the neocarta wheel with the
extra; the per-package wheels and the wheel-bundling hack in the old
`dbxcarta-spark/pyproject.toml` (copying core source into the spark wheel
before building) disappear entirely.

Add a console script so a submitted job has a stable entrypoint without any
repo checkout:

```toml
[project.scripts]
neocarta-databricks-ingest = "neocarta.connectors.databricks.entrypoint:main"
```

Port `dbxcarta/spark/entrypoint.py` (the local tree still has it) as
`neocarta/connectors/databricks/entrypoint.py`. It stays a thin shim that
builds settings from job parameters and calls the connector, and it raises the
same actionable `ImportError` when the extra is missing.

## What the `dbxcarta/` directory becomes

A deployment and examples showcase: how to package, submit, and evaluate the
neocarta Databricks connector as real Databricks jobs. Nothing in it is
published.

```
dbxcarta/
├── README.md              # reframed: "running the neocarta Databricks connector on Databricks"
├── Makefile               # e2e targets per example (bootstrap, ingest, client, teardown)
├── docs/                  # architecture, pipeline, operational lessons (keep; update references)
├── submit/                # was dbxcarta-submit: operator CLI to build the neocarta
│   │                      # wheel, bootstrap UC + secret scope, submit jobs
│   └── ...                # publish-wheels now builds neocarta[databricks-spark], not 5 wheels
├── client/                # was dbxcarta-client: Text2SQL eval harness (graph_rag,
│   │                      # schema_dump, no_context arms) run against the built graph
├── support/               # was the residue of dbxcarta-core: materialize SQL builders,
│   │                      # presets, question shapes, sql_safety guard
├── materialize/           # was dbxcarta-materialize: seeds example blueprints as Delta tables
├── examples/              # dense-schema, finance-genie, schemapile: overlay envs,
│   │                      # questions.json, presets, local demos
└── tests/                 # tests for the local support/client/submit code only
```

Decisions inside this directory:

- **`dbxcarta-spark` is deleted**, including the leftover `pyproject.toml` the
  branch kept. Its tests move to `tests/unit/connectors/databricks/` in the
  main test tree.
- **`dbxcarta-submit` is retargeted, not deleted.** It is the piece that makes
  the directory a runnable showcase: `bootstrap`, `publish-wheels`,
  `submit-entrypoint ingest|client|materialize`, `teardown`, `logs`. Its
  `publish-wheels` builds one wheel, neocarta with the `databricks-spark`
  extra closure, and `submit-entrypoint ingest` invokes
  `neocarta-databricks-ingest`.
- **`dbxcarta-client` stays here**, not in neocarta. It is an evaluation
  harness, the same role `eval/` plays for the BigQuery agent. If pieces of it
  prove generally useful, for example the graph retriever, they can migrate to
  `eval/` or the agent later as a separate decision.
- **Whether to keep these as installable sub-packages or flatten them**: keep
  them as local uv workspace members so `uv run --group dbxcarta` keeps
  working, but they may simply depend on `neocarta` from the workspace root
  instead of on `dbxcarta-core`.
- The dbxcarta `.env` plus overlay-env convention, `setup_secrets.sh`, and the
  per-example `dbxcarta-overlay.env` files all stay. They are operational
  documentation as much as configuration.

## Gaps to close beyond the branch

1. **Connector contract conformance.** `DatabricksSparkSchemaConnector`
   currently exposes only `run(spark)`. Conformance tests assert every
   connector in `neocarta.connectors` matches `SourceConnectorProtocol`
   (`extract` / `transform` / `load` / `ingest`, with `run` as a deprecated
   wrapper). Recommended mapping: `ingest(spark=None)` becomes the public
   orchestrator; `extract`, `transform`, and `load` delegate to the pipeline
   phases (information_schema reads; schema-graph build plus value sampling;
   Spark Connector writes); `run` emits the `DeprecationWarning` and delegates,
   matching the other connectors. The phases hold DataFrames rather than
   Pydantic models, so document that explicitly in the connector docstring. If
   stage-level methods prove artificial for the Spark execution model, the
   alternative is to amend the contract with a documented exemption, but try
   conformance first since the orchestration shape genuinely matches.
2. **Reconcile branch port with the current local tree.** The branch forked
   from `72936d7` and the local `dbxcarta/` has continued evolving, including
   the alignment work in `align-dbxcarta.md` now complete at CONTRACT_VERSION
   1.7, the `verify/` consistency checks, the embedding ledger, and
   `summary_io.py` Delta emission. Re-port from the current
   `dbxcarta-spark` sources, keeping the branch's structural decisions: no
   embed stage, FK inference in enrichment, `_platform` extraction.
3. **Decide the verify and summary-Delta features.** `verify/` and
   `summary_io.py` write to and read from Databricks ops tables. Recommended:
   port them with the connector since they are part of operating the pipeline,
   behind the same extra.
4. **Tests.** Populate `tests/unit/connectors/databricks/` from
   `dbxcarta/tests` for everything that moved, add the connector to the
   protocol conformance tests, and wire `make test-databricks`. Local Spark
   tests need no cluster.
5. **Schema enforcement, Phase 2 of `align-dbxcarta.md`.** The blocking issue
   was that dbxcarta could not depend on neocarta's Pydantic models. In-repo,
   that blocker is gone: the transform stage can validate sampled rows of each
   DataFrame against `neocarta/data_model/rdbms` models before write, without
   PyDeequ. Track as a follow-up, not part of the migration.
6. **Docs and changelog.** Connector README under
   `neocarta/connectors/databricks/`, the main README's connector table, the
   `add-source-connector` skill's contract notes for the Spark execution-model
   caveat, and CHANGELOG.md.

## Migration sequence

1. Rebase or re-create the branch port against current `main`, re-porting from
   the up-to-date `dbxcarta-spark` sources (item 2 above).
2. Finish dissolving `dbxcarta-core`: move `volume_io`, `workspace`,
   `executor`, and the env/config mechanics into `_platform/` and
   `settings.py`; move the scaffolding residue into `dbxcarta/support/`.
3. Add `entrypoint.py` and the `neocarta-databricks-ingest` script; make the
   connector conform to `SourceConnectorProtocol`.
4. Delete `dbxcarta-spark/` and `dbxcarta-core/`; retarget `dbxcarta-submit`
   and `dbxcarta-client` to depend on the root `neocarta` workspace member.
5. Port tests, wire `make test-databricks`, run an end-to-end example
   (`dense-schema`) through `dbxcarta/submit` against a real workspace to
   verify the wheel-build and job-submission path.
6. Rewrite `dbxcarta/README.md` as the "run neocarta on Databricks" guide,
   update the main README and CHANGELOG.
