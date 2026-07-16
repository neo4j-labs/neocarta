# The connector contract

The structure, public API, and conventions every connector in
`neocarta/connectors/` must follow — the contract for both adding new connectors
and maintaining existing ones. It is made executable by
`neocarta/connectors/_base.py` (the runtime-checkable `SourceConnectorProtocol` /
`FormatConnectorProtocol`) and enforced per-connector by a `test_conformance.py`.

This is the reference companion to the `neocarta-add-source-connector` skill's `SKILL.md`,
which covers the operational loop (scaffold / verify / implement). All paths below
are relative to the repo root.

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

    # Context-manager support (all connectors)
    def close(self) -> None:
        """Release resources the connector owns (NOT the injected driver)."""

    def __enter__(self) -> Self:
        """Return self for use as a context manager."""

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Release owned resources on context-manager exit."""
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

## 8b. Search entry points — index requirements

A **search entry point** is any node label that a user or agent searches to enter
the graph — the targets of the MCP full-text / vector / hybrid /
business-term-bridged search tools. Today these are `Table`, `Column`, `Metric`,
and `BusinessTerm`. The defining property is that the node carries
human-meaningful `name` / `description` text and the MCP search tiers are keyed
on its label.

**For every node label your connector treats as a search entry point, the loader
must create at load time:**

1. A **name range index** (exact-equality lookups), and
2. A **full-text index** (`create_full_text_index`), mirroring how the base
   `Neo4jRDBMSLoader` does for `Table` / `Column` / `BusinessTerm`.

**Override hazard:** if you subclass `Neo4jRDBMSLoader` and override a node
loader (e.g. `load_osi_table_nodes`), you inherit the responsibility to recreate
the indexes the base method created. Overriding silently drops them otherwise,
leaving MCP search tiers unregistered for that label.

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

## 9b. Context-manager lifecycle

All connectors support the context-manager protocol:

```python
with FooConnector(neo4j_driver=driver) as connector:
    connector.ingest(...)
# connector-owned resources (e.g. an HTTP client) are released; `driver` stays open
```

- `.close()` releases only resources the connector **created and owns** (e.g. an
  HTTP client it built). The Neo4j driver is **injected by the caller**, so the
  caller owns its lifecycle and `.close()` must **not** close it — closing a
  borrowed driver would break callers that share one driver across connectors or
  reuse it after the `with` block. Connectors that own no extra resources (those
  that only hold the injected driver) have a no-op `.close()`.
- `.__enter__()` returns `self`.
- `.__exit__()` delegates to `.close()` unconditionally.
- A connector that constructs its own client (see the Unity Catalog connector,
  which builds an `httpx.Client`) overrides `.close()` to release it.

## 10. Cross-cutting orchestrator behavior

Both `.ingest()` and `.export()`:
- Call the three stages in order.
- `.ingest()` calls `loader.upsert_neocarta_graph_node()` at the end (records that
  neocarta has touched this graph). Export does not.
- Emit user-facing progress through the module logger (§16), never `print()`. The
  extractor's `@log_stage`-decorated methods cover the extract phase; `.transform()`
  and `.load()` each log a phase line, `.transform()` ends with
  `log_transform_counts(...)`, and `.ingest()` logs the final "completed" line.

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

## 16. Logging

Connectors report progress through Python's `logging`, rooted at the `neocarta`
package logger — never `print()`. Importing neocarta as a library stays silent (a
`NullHandler` is attached to the `neocarta` logger in `neocarta/__init__.py`); only
a host that opts in — chiefly the CLI, via `configure_logging()` — attaches a real
handler. The shared helpers live in
[neocarta/_logging.py](neocarta/_logging.py):

- **Per-module loggers.** Each module that logs does
  `logger = logging.getLogger(__name__)`, giving the
  `neocarta.connectors.<source>.<datatype>.<module>` hierarchy for free. An
  extractor module whose logging is entirely `@log_stage` needs no module logger —
  the decorator derives one from the wrapped method's module.
- **`@log_stage`** decorates extractor methods (e.g. `extract_*_info`) to log a
  one-line INFO summary: humanized method name + optional target + row count +
  elapsed. It never logs SQL or row values, and surfaces only an allowlist of safe
  scalar kwargs (`dataset_id`, `table_name`, `region`, `filename`, …) as the
  target. Pass `@log_stage(count=False)` when the return value has no meaningful
  row count (e.g. an OSI spec dict).
- **`log_transform_counts(logger, transformer, fields)`** logs `"Transformed N
  <label>"` per produced type at the end of `.transform()`. `fields` is a tuple of
  `(human_label, transformer_attribute)` pairs the connector declares as a module
  constant (`_TRANSFORM_COUNTS`); zero-count types are skipped so an empty phase
  stays quiet.
- **`log_timing(logger, label, *, target=None)`** is a context-manager escape hatch
  for code paths `@log_stage` doesn't fit (e.g. a helper with early-return
  branches).
- **The loader logs its own writes** by graph pattern plus merge counters (e.g.
  `Ingested (:Column)-[:TAGGED_WITH]->(:BusinessTerm) — created 12, properties_set
  24`). Don't re-log per-type load counts inside `.load()`.

**Never log data values.** SQL text, row values, full provider error bodies, API
keys, and description / embedding payloads must not reach the log — log counts,
labels, dimensions, and targets (allowlisted scalars) only. When catching a
provider/parse error, log the exception *type*, not its message
(`logger.warning("Embedding request failed (%s)", type(exc).__name__)`).

The scaffold wires this up: generated extractors decorate `extract()` with
`@log_stage`, and the generated connector defines `_TRANSFORM_COUNTS`, calls
`log_transform_counts`, and logs each phase through the module logger — no
`print()`. `verify` warns on any stray `print()` in connector code, so don't
introduce any.
