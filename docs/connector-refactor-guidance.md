# Connector Standard


This document defines the structure, public API, and conventions every connector in `neocarta/connectors/` must follow. It is the contract for both adding new connectors and migrating existing ones.


## 1. Connector kinds


Connectors fall into one of two kinds. The kind determines the directory layout and the supported operations.


### Source connector


Reads metadata from an external system (database, catalog API, log store) and ingests it into Neo4j. Examples: BigQuery, Dataplex, query log files.


- Operations: **ingest only**.
- Directory layout: sub-folders by **data type** (`schema/`, `glossary/`, `query_log/`, …). Each sub-folder is itself a connector and follows the same contract.
- Reason for the split: a single source often exposes multiple kinds of information via different APIs; treating each as its own connector keeps responsibilities narrow.


### Format connector


Reads/writes a portable file format that can express any of the graph entity types. Examples: CSV, OSI YAML.


- Operations: **ingest and (optionally) export**.
- Directory layout: sub-folders by **direction** (`ingest/`, `export/`). The connector class lives at the package root; per-direction stages live under the matching sub-folder.
- Reason for the split: ingest and export are symmetric but distinct ETL pipelines; sharing a folder muddles which extractor/transformer belongs to which direction.


Export belongs only to format connectors. Source connectors do not export — neocarta does not write back to external catalogs.


## 2. Directory layout


### Source connector — e.g. `bigquery/`


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
 query_log/
   __init__.py          # exports BigQueryLogsConnector
   connector.py
   extract.py
   transform.py
```


### Format connector — e.g. `osi/`


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


The CSV connector migrates from flat to this layout once `.export()` is added; until then, only `ingest/` is required.


## 3. Public API


Every connector exposes the same shape. The orchestrator methods (`.ingest()`, `.export()`) call the three stages in order and perform any cross-cutting bookkeeping (e.g. `upsert_neocarta_graph_node()`).


### Source connector (ingest only)


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
```


### Format connector (ingest + export)


```python
class FooConnector:
   SUPPORTED_VERSIONS: tuple[str, ...] = (...)   # optional, format-specific


   def __init__(self, ...long-lived resources...) -> None: ...


   # ingest path
   def extract(self, source, *, version=..., include_nodes=None, include_relationships=None) -> None: ...
   def transform(self) -> None: ...
   def load(self) -> None: ...
   def ingest(self, source, *, version=..., include_nodes=None, include_relationships=None) -> None: ...


   # export path
   def export(
       self,
       ...filter kwargs (e.g. semantic_model_name)...,
       output_path: str | Path,
   ) -> None:
       """extract from Neo4j → transform → write to file."""
```


The ingest direction's three stages (`extract` / `transform` / `load`) plus `.ingest()` are public. The export direction is exposed as a single public `.export()` orchestrator — its internal stages (graph read, source-format build, file write) live on private helpers / locals and are not part of the public surface. This keeps the format-connector contract symmetric with source connectors on the inbound direction without doubling the public stage method count for the outbound direction.


Serialization helpers used by `.export()` (e.g. `OsiExportTransformer.to_yaml()`, future `CSVExportTransformer.to_csv()`) live on the underlying transformer classes; they're called from inside `.export()` and never exposed on the connector directly.


## 4. Configuration: constructor vs method


The rule decides what goes where:


- **Constructor** — anything stable for the lifetime of the connector instance: Neo4j driver, database name, BQ client, project id, CSV directory whose contents follow a known-name convention, HTTP timeout.
- **Method (`.ingest()` / `.export()` / `.extract()`)** — anything that varies per call: a single OSI spec file/URL, a BigQuery dataset id, a query log file path, a query time window, the OSI spec version, the semantic model name to export, the output file path.


Examples:


- CSV: directory of known-name files → constructor. (CSV is built to read many files in one pass; the directory IS the long-lived resource.)
- OSI: each spec file is an ad-hoc input; one connector instance may ingest several different files → `.ingest(spec_source, version=...)` takes both.
- BigQuery: client + project → constructor; dataset id → method (varies per call).


## 5. Filtering: `include_nodes` / `include_relationships`


When a connector supports selective loading, it uses these two parameters with values from the `NodeLabel` / `RelationshipType` enums.


- The parameters are passed on `.extract()` and forwarded by `.ingest()`.
- Filtering controls what gets **cached** for the next stage. If an entity must be extracted purely to resolve associations (e.g. tables needed to attach columns to schemas) but the caller asked to exclude that type, the extractor uses it transiently but does not write it to the cache.
- `None` (the default) means "include everything available."


Connectors that don't yet support filtering may omit the parameters until they do. Once added, they must use these names and the shared enums — no bespoke flags like `include_schema` / `include_glossary`.


### Narrow exception: bespoke flags for non-graph-shape choices


`include_nodes` / `include_relationships` exist to control *which entity types in the unified graph schema* a connector produces. They are not the right tool for choices that don't map cleanly onto a node or relationship type:


- Whether to make extra network round trips (e.g. an extra REST API the connector could skip).
- Whether to attach metadata that spans multiple node/relationship types in a way the enum can't express on its own.
- Optional connector-specific phases that don't add new entity types but change how existing ones are populated.


For these, a connector **may** introduce a bespoke boolean flag (e.g. `include_entry_links` on `DataplexGlossaryConnector`) with the following rules:


- The flag is keyword-only on `extract()` and forwarded by `ingest()` / `export()`.
- The flag has a sensible default (usually `True` — i.e. the richer behavior is the default).
- The docstring explains *what would otherwise differ* if the flag were folded into `include_nodes` / `include_relationships`, and why that representation would be wrong or lossy.
- The flag never controls visibility of an entity type that's already addressable via the enums. Use the enums for those cases.


Bespoke flags are an escape hatch, not the standard. Reach for them when the enums genuinely can't express the choice; otherwise use the enums.


## 6. Versioning (format connectors only)


File formats evolve; source-side catalog APIs are versioned by the vendor and we just consume what they give us. Therefore:


- **Format connectors** *may* declare `SUPPORTED_VERSIONS: tuple[str, ...]` on the class and accept a `version: str` kwarg on `.ingest()`.
- The connector emits a typed warning (see §7) if the declared `version` is outside `SUPPORTED_VERSIONS`, or if the parsed file's version field is missing or mismatched.
- Version is an ingest-time compatibility check only. `.export()` re-emits whatever version was stored on the originating graph node — it has no `version` argument.
- **Source connectors** do not expose `version` / `SUPPORTED_VERSIONS`.


## 7. Errors and warnings


The rule:


- **Raise** when the run cannot proceed correctly. Missing configuration (no project id, no Neo4j driver), unreachable resources, malformed inputs that can't be parsed at all. Use the typed errors in `neocarta/errors.py` (`ConfigError`, etc.).
- **Warn** when the run can proceed but the result is degraded. Unknown spec versions, missing optional relationships, fields the format permits but the source omitted. Use a typed warning subclass rooted in `neocarta/warnings.py:NeocartaWarning` so callers can filter the specific category without silencing all `UserWarning`s.


Connector-specific warning classes (e.g. `UnsupportedOsiVersionWarning`) live in `neocarta/warnings.py` and are re-exported from the connector's `__init__.py` for discoverability.


## 8. Loader scoping


Most connectors use the shared `Neo4jRDBMSLoader` (`neocarta.ingest.rdbms`). A connector defines its own loader subclass only when it needs source-specific writes — e.g. additional labels, ON CREATE semantics, or node types not covered by the base loader.


- Source-specific loaders live at the connector package root (`osi/load.py`), not inside an `ingest/` or `export/` sub-folder.
- They subclass `Neo4jRDBMSLoader`; they do not reimplement it.


## 9. Cache and lifecycle


Internal cached state on the extractor and transformer is **not part of the public API**. Users interact only through the connector's stage methods.


Lifecycle rules:


- Each call to `.extract()` replaces the extractor's cached state (no implicit accumulation across calls).
- `.transform()` requires a prior successful `.extract()` on the same instance.
- `.load()` requires a prior successful `.transform()`.
- `.ingest()` and `.export()` are end-to-end runs; calling them N times against the same instance is equivalent to N independent runs against the same Neo4j / file target.


## 10. Cross-cutting orchestrator behavior


Both `.ingest()` and `.export()` are responsible for:


- Calling the three stages in order.
- Calling `loader.upsert_neocarta_graph_node()` at the end of an `.ingest()` (records that neocarta has touched this graph). Export does not call it.
- User-facing progress logging (the existing `print("Extracting...")` style — left as `print()` for now; logging upgrade is out of scope for this doc).


## 11. `__init__.py` exports


Each connector package's `__init__.py` exports:


- The connector class(es).
- Any connector-specific typed warnings/errors.


It does **not** export the internal extractor, transformer, or loader classes. If a future use case requires direct access, expose them then. Until then, keep the public surface minimal.


```python
# osi/__init__.py
from .connector import OsiConnector


__all__ = ["OsiConnector"]
```


## 12. Required README


Every connector ships a `README.md` at its package root. Sections, in order:


1. **Overview** — one paragraph: what source/format, what gets into Neo4j, any attribution.
2. **Connector type** — source or format; for source, the data-type sub-connectors it provides (schema / glossary / query_log).
3. **Data model** — mermaid diagram of the nodes and relationships this connector produces, with node properties and key markers.
4. **Usage**
  - Minimal code example: imports, driver setup, constructor call, `.ingest()` call.
  - Environment variables (Neo4j connection vars at minimum; source-specific auth vars if any).
  - Filtering options — which `NodeLabel` / `RelationshipType` values apply.
  - Round-trip / export example — format connectors only.
5. **Version compatibility** — format connectors only. List `SUPPORTED_VERSIONS` and what changes between supported versions.
6. **Source-specific setup** — how to obtain credentials, export the input file, configure the upstream system. Skip if N/A.
7. **Known issues / limitations**.


## 13. Migration: deprecating `.run()`


Existing connectors expose `.run()` as the orchestrator. Migration:


- Add `.ingest()` with the signature above.
- Keep `.run()` as a thin wrapper that calls `.ingest()` and emits a `DeprecationWarning`.
- Remove `.run()` after approximately three releases.


The `.run()` shim does not need to be a full re-implementation — delegate to `.ingest()` and let the warning surface to callers.


## 14. Style and id generation


- Code style: numpy docstrings, ruff format + lint (see project `CLAUDE.md`).
- All node id generation must route through `neocarta/connectors/utils/generate_id.py` — never inline an f-string for an id. Add a new function in `generate_id.py` if no existing one fits.


## 15. Identifying the connector kind at a glance


| Trait | Source connector | Format connector |
|-------|------------------|------------------|
| Reads from | External system (DB, catalog API, log store) | File (local path or URL) |
| Writes to | Neo4j only | Neo4j (ingest) + file (export) |
| Sub-folders | By data type (`schema/`, `glossary/`, `query_log/`) | By direction (`ingest/`, `export/`) |
| Exposes `.export()` | No | Yes (when round-trip is meaningful) |
| Exposes `SUPPORTED_VERSIONS` / `version` arg | No | Optional |
| Examples | BigQuery, Dataplex, query log file reader | CSV, OSI |



