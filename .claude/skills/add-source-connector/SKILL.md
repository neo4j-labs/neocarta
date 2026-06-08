---
name: add-source-connector
description: Scaffold, build, and verify a neocarta source or format connector against the connector contract. Use when asked to add/create/scaffold/write a new connector (BigQuery, Dataplex, query log, CSV, OSI, etc.), port a data source into neocarta, or check that a connector conforms to the standard.
---

Build a new connector under `neocarta/connectors/` that satisfies the connector
contract. This file **is** the contract — the prose standard plus the operational
loop for authoring one. The contract is also made executable in
[neocarta/connectors/_base.py](neocarta/connectors/_base.py) (runtime-checkable
`SourceConnectorProtocol` / `FormatConnectorProtocol`) and enforced per-connector
by a `test_conformance.py`. Drive the whole loop with the driver:
`.claude/skills/add-source-connector/driver.py`, run through `uv`.

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
uv run .claude/skills/add-source-connector/driver.py list

# Scaffold a new flat source connector (creates package + conformance test):
uv run .claude/skills/add-source-connector/driver.py scaffold salesforce

# A data-type sub-connector (sub-folder under a parent source):
uv run .claude/skills/add-source-connector/driver.py scaffold salesforce/schema

# A format connector (adds the export() orchestrator):
uv run .claude/skills/add-source-connector/driver.py scaffold acme_yaml --format

# Verify any connector against the contract (static checks + conformance pytest):
uv run .claude/skills/add-source-connector/driver.py verify salesforce
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
   accessors), `transform.py` (build `data_model` objects via `generate_id`
   helpers), and the `load()` body (call `self.loader.load_*` for your node /
   relationship types).
3. Fill in the `README.md` (see [§12 Required README](#12-required-readme)).
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

# The connector contract

The structure, public API, and conventions every connector in
`neocarta/connectors/` must follow — the contract for both adding new connectors
and maintaining existing ones.

## 1. Connector kinds

Connectors fall into one of two kinds. The kind determines the directory layout
and supported operations.

**Source connector** — reads metadata from an external system (database, catalog
API, log store) and ingests into Neo4j. Examples: BigQuery, Dataplex, query log
files.
- Operations: **ingest only**.
- Layout: sub-folders by **data type** (`schema/`, `glossary/`, `query_log/`, …).
  Each sub-folder is itself a connector and follows the same contract.
- A single source often exposes multiple kinds of information via different APIs;
  treating each as its own connector keeps responsibilities narrow. A source that
  exposes only one data type may be flat (e.g. `query_log/`).

**Format connector** — reads/writes a portable file format that can express any
graph entity type. Examples: CSV, OSI YAML.
- Operations: **ingest and (optionally) export**.
- Layout: sub-folders by **direction** (`ingest/`, `export/`). The connector
  class lives at the package root; per-direction stages live under the matching
  sub-folder.
- Ingest and export are symmetric but distinct ETL pipelines; separate folders
  keep clear which extractor/transformer belongs to which direction.

Export belongs only to format connectors. Source connectors do not export —
neocarta does not write back to external catalogs.

## 2. Directory layout

Source connector — e.g. `bigquery/`:

```
bigquery/
 __init__.py            # exports BigQuerySchemaConnector, BigQueryLogsConnector
 README.md
 schema/
   __init__.py          # exports BigQuerySchemaConnector
   connector.py
   extract.py
   transform.py
   models.py            # extract-stage typed dicts, if needed
 logs/
   __init__.py          # exports BigQueryLogsConnector
   connector.py
   extract.py
   transform.py
```

Format connector — e.g. `osi/`:

```
osi/
 __init__.py            # exports OsiConnector + connector-specific warnings
 README.md
 connector.py           # the OsiConnector class
 load.py                # source-specific loader, if needed (else omit)
 ingest/
   __init__.py
   extract.py
   transform.py
 export/
   __init__.py
   extract.py
   transform.py
```

The CSV connector is currently flat (`ingest/` only) and migrates to the
directional layout once `.export()` is added.

## 3. Public API

Every connector exposes the same shape. The orchestrators (`.ingest()`,
`.export()`) call the three stages in order and perform cross-cutting bookkeeping
(e.g. `upsert_neocarta_graph_node()`).

Source connector (ingest only):

```python
class FooConnector:
    def __init__(self, ...long-lived resources...) -> None: ...

    def extract(
        self,
        ...source-specific kwargs...,
        *,
        include_nodes: list[NodeLabel] | None = None,
        include_relationships: list[RelationshipType] | None = None,
    ) -> None: ...

    def transform(self) -> None: ...
    def load(self) -> None: ...

    def ingest(
        self,
        ...source-specific kwargs...,
        *,
        include_nodes: list[NodeLabel] | None = None,
        include_relationships: list[RelationshipType] | None = None,
    ) -> None:
        """extract → transform → load → upsert_neocarta_graph_node."""

    def run(self, ...) -> None:
        """Deprecated shim — emits DeprecationWarning, delegates to ingest()."""
```

Format connector (ingest + export) adds:

```python
class FooConnector:
    SUPPORTED_VERSIONS: tuple[str, ...] = (...)   # optional, format-specific

    def extract(self, source, *, version=..., include_nodes=None, include_relationships=None) -> None: ...
    def transform(self) -> None: ...
    def load(self) -> None: ...
    def ingest(self, source, *, version=..., include_nodes=None, include_relationships=None) -> None: ...

    def export(
        self,
        ...filter kwargs (e.g. semantic_model_name)...,
        output_path: str | Path,
    ) -> None:
        """extract from Neo4j → transform → write to file."""
```

The ingest direction's three stages plus `.ingest()` are public. The export
direction is exposed as a single public `.export()` orchestrator — its internal
stages (graph read, source-format build, file write) live on private helpers /
locals and are not part of the public surface. This keeps the format-connector
contract symmetric with source connectors on the inbound direction without
doubling the public stage method count outbound.

Serialization helpers used by `.export()` (e.g. `OsiExportTransformer.to_yaml()`,
future `CSVExportTransformer.to_csv()`) live on the underlying transformer
classes; they're called from inside `.export()` and never exposed on the
connector directly.

## 4. Configuration: constructor vs method

- **Constructor** — anything stable for the connector instance's lifetime: Neo4j
  driver, database name, BQ client, project id, a CSV directory whose contents
  follow a known-name convention, HTTP timeout.
- **Method (`.ingest()` / `.export()` / `.extract()`)** — anything that varies
  per call: a single OSI spec file/URL, a BigQuery dataset id, a query log file
  path, a query time window, the OSI spec version, the semantic model name to
  export, the output file path.

Examples:
- CSV: directory of known-name files → constructor (the directory IS the
  long-lived resource; CSV reads many files in one pass).
- OSI: each spec file is ad-hoc; one instance may ingest several →
  `.ingest(spec_source, version=...)` takes both.
- BigQuery: client + project → constructor; dataset id → method.

## 5. Filtering: `include_nodes` / `include_relationships`

When a connector supports selective loading, it uses these two parameters with
values from the `NodeLabel` / `RelationshipType` enums (`neocarta.connectors.utils`).

- Passed on `.extract()` and forwarded by `.ingest()`.
- Filtering controls what gets **cached** for the next stage. If an entity must be
  extracted purely to resolve associations (e.g. tables needed to attach columns
  to schemas) but the caller excluded that type, the extractor uses it transiently
  but does not write it to the cache.
- `None` (default) means "include everything available."

Connectors without filtering may omit the parameters until they add it. Once
added, they must use these names and the shared enums — no bespoke flags like
`include_schema` / `include_glossary`.

**Narrow exception — bespoke flags for non-graph-shape choices.** `include_nodes`
/ `include_relationships` control *which entity types in the unified graph schema*
a connector produces. They are not the tool for choices that don't map cleanly
onto a node/relationship type:
- Whether to make extra network round trips (e.g. an extra REST API).
- Whether to attach metadata spanning multiple node/relationship types in a way
  the enum can't express.
- Optional connector-specific phases that change how existing entity types are
  populated without adding new ones.

For these a connector **may** introduce a bespoke boolean flag (e.g.
`include_entry_links` on `DataplexGlossaryConnector`):
- Keyword-only on `extract()`, forwarded by `ingest()` / `export()`.
- Sensible default (usually `True` — the richer behavior is default).
- Docstring explains *what would otherwise differ* if folded into the enums, and
  why that representation would be wrong or lossy.
- Never controls visibility of an entity type already addressable via the enums.

Bespoke flags are an escape hatch, not the standard.

## 6. Versioning (format connectors only)

File formats evolve; source-side catalog APIs are vendor-versioned and we consume
what they give us. Therefore:
- **Format connectors** *may* declare `SUPPORTED_VERSIONS: tuple[str, ...]` and
  accept a `version: str` kwarg on `.ingest()`.
- The connector emits a typed warning (§7) if `version` is outside
  `SUPPORTED_VERSIONS`, or if the parsed file's version field is missing/mismatched.
- Version is an ingest-time compatibility check only. `.export()` re-emits whatever
  version was stored on the originating graph node — it has no `version` argument.
- **Source connectors** do not expose `version` / `SUPPORTED_VERSIONS`.

## 7. Errors and warnings

- **Raise** when the run cannot proceed correctly: missing configuration (no
  project id, no Neo4j driver), unreachable resources, inputs that can't be parsed
  at all. Use the typed errors in `neocarta/errors.py` (`ConfigError`, `StateError`, …).
- **Warn** when the run proceeds but degraded: unknown spec versions, missing
  optional relationships, fields the format permits but the source omitted. Use a
  typed warning subclass rooted in `neocarta/warnings.py:NeocartaWarning` so
  callers can filter the category without silencing all `UserWarning`s.

Connector-specific warning classes (e.g. `UnsupportedOsiVersionWarning`) live in
`neocarta/warnings.py` and are re-exported from the connector's `__init__.py` for
discoverability.

## 8. Loader scoping

Most connectors use the shared `Neo4jRDBMSLoader` (`neocarta.ingest.rdbms`). Define
a loader subclass only when you need source-specific writes — additional labels,
ON CREATE semantics, or node types the base loader doesn't cover.
- Source-specific loaders live at the connector package root (`osi/load.py`), not
  inside an `ingest/` or `export/` sub-folder.
- They subclass `Neo4jRDBMSLoader`; they do not reimplement it.

## 9. Cache and lifecycle

Internal cached state on the extractor and transformer is **not part of the public
API**. Users interact only through the connector's stage methods.

- Each `.extract()` replaces the extractor's cached state (no implicit accumulation
  across calls) and resets the downstream `_extracted` / `_transformed` flags.
- `.transform()` requires a prior successful `.extract()` on the same instance.
- `.load()` requires a prior successful `.transform()` (checks `_transformed`, not
  `_extracted`).
- `.ingest()` / `.export()` are end-to-end runs; calling them N times against the
  same instance equals N independent runs against the same Neo4j / file target.

## 10. Cross-cutting orchestrator behavior

Both `.ingest()` and `.export()`:
- Call the three stages in order.
- `.ingest()` calls `loader.upsert_neocarta_graph_node()` at the end (records that
  neocarta has touched this graph). Export does not.
- Do user-facing progress logging (the existing `print("Extracting...")` style —
  `print()` for now; logging upgrade is out of scope).

## 11. `__init__.py` exports

Each connector package's `__init__.py` exports only:
- The connector class(es).
- Any connector-specific typed warnings/errors.

It does **not** export the internal extractor, transformer, or loader classes.
Keep the public surface minimal; expose internals only when a concrete use case
requires it.

```python
# osi/__init__.py
from .connector import OsiConnector

__all__ = ["OsiConnector"]
```

## 12. Required README

Every connector ships a `README.md` at its package root. Sections, in order:
1. **Overview** — one paragraph: what source/format, what gets into Neo4j, any attribution.
2. **Connector type** — source or format; for source, the data-type sub-connectors it provides.
3. **Data model** — mermaid diagram of nodes and relationships produced, with node properties and key markers.
4. **Usage** — minimal code example (imports, driver setup, constructor, `.ingest()`); environment variables (Neo4j vars + source auth); filtering options (which `NodeLabel` / `RelationshipType` apply); round-trip/export example (format connectors only).
5. **Version compatibility** — format connectors only. `SUPPORTED_VERSIONS` and what changes between them.
6. **Source-specific setup** — credentials, export the input file, configure upstream. Skip if N/A.
7. **Known issues / limitations**.

## 13. The deprecated `.run()` shim

`run()` is part of the protocol (and the conformance test asserts it) but is
deprecated in favor of `ingest()`. Every connector keeps a thin `run()` that emits
a `DeprecationWarning` and delegates to `ingest()` — it does not re-implement the
pipeline. The scaffold generates this correctly.

## 14. Style and id generation

- Code style: numpy docstrings, ruff format + lint (see project `CLAUDE.md`).
- **All node id generation must route through
  [neocarta/connectors/utils/generate_id.py](neocarta/connectors/utils/generate_id.py)** —
  never inline an f-string for an id. Add a new function there if none fits.
  `verify` flags inline id f-strings.

## 15. Identifying the connector kind at a glance

| Trait | Source connector | Format connector |
|-------|------------------|------------------|
| Reads from | External system (DB, catalog API, log store) | File (local path or URL) |
| Writes to | Neo4j only | Neo4j (ingest) + file (export) |
| Sub-folders | By data type (`schema/`, `glossary/`, `logs/`) | By direction (`ingest/`, `export/`) |
| Exposes `.export()` | No | Yes (when round-trip is meaningful) |
| Exposes `SUPPORTED_VERSIONS` / `version` | No | Optional |
| Examples | BigQuery, Dataplex, query log | CSV, OSI |

---

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

## Troubleshooting

- **`verify` FAIL: `DID NOT WARN ... connector.run()` / `missing 1 required positional argument`** —
  your `run()`/`ingest()` require a positional the conformance test doesn't pass.
  Either default the arg to `None` or update the generated test to pass one.
- **`list` shows `(no exported connector)`** (e.g. `databricks`) — the package's
  `__init__.py` doesn't export a `*Connector` in `__all__` yet (work in progress).
- **`verify` FAIL: `cannot import ...`** — missing optional dep for that source
  (e.g. `google.cloud.bigquery`). `uv sync --all-groups` pulls the lot.
