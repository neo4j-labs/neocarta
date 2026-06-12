---
name: neocarta-add-source-connector
description: Scaffold, build, and verify a neocarta source or format connector against the connector contract. Use when asked to add/create/scaffold/write a new connector (BigQuery, Dataplex, query log, CSV, OSI, etc.), port a data source into neocarta, or check that a connector conforms to the standard.
---

Build a new connector under `neocarta/connectors/` that satisfies the connector
contract. This file is the **operational loop** for authoring one; the full prose
standard lives in
[connector-contract.md](.claude/skills/neocarta-add-source-connector/connector-contract.md)
(read it before designing a connector). The contract is also made executable in
[neocarta/connectors/_base.py](neocarta/connectors/_base.py) (runtime-checkable
`SourceConnectorProtocol` / `FormatConnectorProtocol`) and enforced per-connector
by a `test_conformance.py`. Drive the whole loop with the driver:
`.claude/skills/neocarta-add-source-connector/scripts/driver.py`, run through `uv`.

All paths below are relative to the repo root.

## Scope: one connector, one PR

Building the connector library package and wiring it into the `neocarta` CLI are
**separate PRs**. This skill covers only the library connector — the package under
`neocarta/connectors/`, its tests, and its README. Do **not** add a CLI subcommand
(`neocarta/_cli/`) in the same PR. CLI integration lands in a follow-up PR.

## Prerequisites

The managed environment only — no system packages needed for scaffold/verify.

```bash
uv sync --all-groups
```

Running the **integration** tests (a real ingest into Neo4j) additionally needs
Docker — the suite spins up a Neo4j testcontainer (`tests/integration/conftest.py`).

## Run (agent path) — the driver

```bash
# See every connector and its detected kind (source/format):
uv run .claude/skills/neocarta-add-source-connector/scripts/driver.py list

# Scaffold a new flat source connector (creates package + conformance test):
uv run .claude/skills/neocarta-add-source-connector/scripts/driver.py scaffold salesforce

# A data-type sub-connector (sub-folder under a parent source):
uv run .claude/skills/neocarta-add-source-connector/scripts/driver.py scaffold salesforce/schema

# A format connector (adds the export() orchestrator):
uv run .claude/skills/neocarta-add-source-connector/scripts/driver.py scaffold acme_yaml --format

# Verify any connector against the contract (static checks + conformance pytest):
uv run .claude/skills/neocarta-add-source-connector/scripts/driver.py verify salesforce
```

`<pkg>` is a path under `neocarta/connectors/`. `--class-name` overrides the
derived class name; `--force` overwrites a non-empty package dir.

`scaffold` writes a conformant skeleton: `__init__.py`, `connector.py` (all
stage methods with the state-guard + deprecation-shim wiring already correct),
`extract.py`, `transform.py`, `README.md`, and
`tests/unit/connectors/<pkg>/test_conformance.py`. The skeleton **passes verify
as-is** — you then fill the `TODO`s in extract/transform/load.

`verify` reports import + protocol conformance (`source` vs `format`, via
`issubclass`), `__all__` minimalism, `README.md` presence, inline-id-f-string
warnings, then runs the connector's `test_conformance.py`. It exits non-zero on
any FAIL. Warnings (e.g. an id f-string) don't fail the run but should be fixed.

### Typical workflow

1. `scaffold` the package (flat, sub-connector, or `--format`).
2. Implement `extract.py` (populate the extractor cache, expose `@property`
   accessors, decorate `extract_*_info` methods with `@log_stage`), `transform.py`
   (build `data_model` objects via `generate_id` helpers), and the `load()` body
   (call `self.loader.load_*` for your node / relationship types). Fill
   `_TRANSFORM_COUNTS` so `log_transform_counts` reports per-type counts — see
   logging conventions in [contract §16](.claude/skills/neocarta-add-source-connector/connector-contract.md#16-logging).
3. Fill in the `README.md` (see [contract §12](.claude/skills/neocarta-add-source-connector/connector-contract.md#12-required-readme)).
4. `verify` until green. Add behavior-specific unit tests beyond conformance.
5. Run the full unit suite + ruff (see Test), update `CHANGELOG.md`.

## Test

```bash
make test-unit          # all unit tests
make fmt && make lint   # ruff format + lint — must be clean before PR
make test-it            # integration: real ingest into a Neo4j testcontainer (Docker)
```

Both the driver and the code it scaffolds are held to the project's
`select = ["ALL"]` ruff rules — a freshly scaffolded connector is lint-clean and
format-clean as generated, so `make lint` stays green before you've written any
implementation. The stub `extract()` / `export()` bodies raise
`NotImplementedError` until you implement them.

---

## The connector contract

The full standard — connector kinds, directory layout, the public stage API,
constructor-vs-method config, filtering, versioning, errors/warnings, loader
scoping, lifecycle, `__init__` exports, the required README, and id generation —
lives in
[connector-contract.md](.claude/skills/neocarta-add-source-connector/connector-contract.md).
**Read it before designing a connector.** `_base.py` and every
`test_conformance.py` cite it as the canonical reference.

## Gotchas

- **Per-call source args default to `None` in the skeleton**
  (`extract(self, source: str | None = None)`, `ingest`, `run`). This is
  deliberate: the conformance test calls `connector.run()` argless to assert the
  `DeprecationWarning`, mirroring how `CSVConnector` (whose inputs live on the
  constructor) is tested. Replace `source` with the real signature/type once the
  source inputs are known — but if you make an arg required, update the generated
  `run` test to pass one.
- **Constructor vs method config** (§4): long-lived resources on `__init__`,
  per-call inputs on `extract`/`ingest`.
- **Sub-connector parent `__init__.py`**: scaffolding `foo/schema` leaves a stub
  `foo/__init__.py` — add the `from .schema import FooSchemaConnector` re-export
  yourself (see `bigquery/__init__.py`).
- **Filtering uses the shared enums** (§5), not bespoke flags, unless the choice
  genuinely can't be expressed as a node/relationship type.
- **Source connectors never expose `version` / `SUPPORTED_VERSIONS` or `export`** —
  format-connector only.
- **Don't re-export internals**: keeping `*Extractor`/`*Transformer`/`*Loader` out
  of `__all__` is enforced by both `verify` and the conformance test.
- **Log, don't `print()`** (§16): progress goes through the module logger
  (`logging.getLogger(__name__)`). Decorate the real `extract_*_info` methods with
  `@log_stage`, fill `_TRANSFORM_COUNTS` so `log_transform_counts` reports per-type
  counts, and let the loader log its own per-pattern write counts. Never log SQL,
  row values, or secrets — counts, labels, targets, and elapsed only. The scaffold
  generates this wiring; `verify` does not flag stray `print()`, so don't add any.

## Troubleshooting

- **`verify` FAIL: `DID NOT WARN ... connector.run()` / `missing 1 required positional argument`** —
  your `run()`/`ingest()` require a positional the conformance test doesn't pass.
  Either default the arg to `None` or update the generated test to pass one.
- **`list` shows `(no exported connector)`** (e.g. `databricks`) — the package's
  `__init__.py` doesn't export a `*Connector` in `__all__` yet (work in progress).
- **`verify` FAIL: `cannot import ...`** — missing optional dep for that source
  (e.g. `google.cloud.bigquery`). `uv sync --all-groups` pulls the lot.
