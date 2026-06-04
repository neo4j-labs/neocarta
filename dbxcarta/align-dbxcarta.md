# Plan: Align the dbxcarta Graph Schema with neocarta's Core RDBMS Model

This plan describes how to bring the graph schema that `dbxcarta/` writes into
Neo4j in line with the canonical neocarta schema defined in
`neocarta/data_model/rdbms/core.py`.

## Core Goals and Objectives

- **One shared graph shape.** A graph built by dbxcarta from Unity Catalog
  should look the same as a graph built by a neocarta connector (BigQuery, CSV,
  etc.). Same node labels, same property names, same relationship structure.
- **Interoperable downstream tooling.** The neocarta agent, MCP tools, and
  retrieval pipelines are written against the core schema. If dbxcarta matches
  it, those tools work on a dbxcarta graph without special-casing.
- **The neocarta core model is the target.** dbxcarta is the side that changes.
  We are not changing `core.py`; we are mapping dbxcarta's output onto it.
- **No legacy to preserve.** There is no existing dbxcarta graph to migrate and
  no backward-compatibility requirement. dbxcarta property names, relationship
  names, **and id formats can all be changed outright** to match neocarta. Every
  run is a clean rebuild, so we are free to pick whatever matches the core
  schema and the neocarta connectors.
- **Scope is the core model only.** The target is the four core nodes
  (Database, Schema, Table, Column) and four core relationships (HAS_SCHEMA,
  HAS_TABLE, HAS_COLUMN, REFERENCES). The richer "expanded" concepts (Value,
  business terms, metrics, queries, OSI model) are out of scope for this pass.
- **Keep dbxcarta's strengths.** Alignment should not throw away the useful
  extra signal dbxcarta produces (medallion layer, FK confidence scores,
  structural identity columns). The aim is to rename and reshape to match the
  core, while treating genuinely extra data as additive properties, not as
  conflicting ones.
- **Two phases: align first, enforce later.** The first pass only makes the
  schema match — rename, reshape, and align ids so the output looks like the
  core model. It does **not** add any validation or enforcement. A later phase
  adds runtime enforcement (see Phase 2) that checks every batch against the
  shape derived from the neocarta Pydantic models. Splitting it this way keeps
  the first pass small and low-risk and lets us prove the aligned graph works
  before we start failing batches on shape violations.

## Phase 1 — Align the Schema (no enforcement)

This phase only changes the *shape* of what dbxcarta emits so it matches the
core model. There is no validation, no fail-closed shape check, no Pydantic in
the pipeline. We rename fields, fill the small gaps, and align ids. That is all.

The differences fall into a few buckets. Today dbxcarta defines its schema as
enums and property lists in `dbxcarta/dbxcarta-spark/.../contract.py` and builds
the node/relationship DataFrames in `schema_graph.py`. The neocarta core defines
it as Pydantic models. The work is to make the property names and shapes match.

### Sub-phases (implement and test each before the next)

Phase 1 is split into independently testable sub-phases by risk tier:

- **1a — Node property renames.** `comment` → `description`, `data_type` →
  `type`, `is_nullable` → `nullable`. Mechanical but wide. **Scoping insight:**
  the `information_schema` columns are literally named `comment`/`data_type`/
  `is_nullable`, and the FK inference reads those same extracted frames, so we
  rename **only at the node-builder `.select()` boundary** (alias there) and
  leave the extract and FK internals on the Unity Catalog names. That confines
  the change to the contract property lists + embedding-text exprs, the node
  builders, the `data_type` index in `neo4j_io.py`, the verify checks, the
  client read layer (retriever / graph_retriever / schema_dump), tests, and
  `docs/schema/SCHEMA.md`.
- **1b — Database descriptive fields.** Add `platform`, `service`,
  `description` to the Database node and contract. `service = "DATABRICKS"`,
  `platform` from config where known (else null), `description` null unless
  sourced. Small and additive.
- **1c — Column `is_primary_key` / `is_foreign_key`.** The hard one. Note the
  **ordering problem:** node writes happen at `run.py` *before* `run_fk_discovery`,
  so `is_foreign_key` cannot be set during the node-write pass without either
  reordering the pipeline (run FK discovery before column-node writes) or adding
  a second-pass property update. PK has no node-facing source today (only the FK
  layer's driver-collected `ConstraintRow`); marking nodes wants a
  `key_column_usage` join instead. Own design decision, own tests.
- **1d — REFERENCES endpoint rename.** `source_id` / `target_id` →
  `source_column_id` / `target_column_id`. **Finding:** these are transient
  DataFrame join columns the Neo4j Spark connector uses to match start/end nodes
  (`relationship.source.node.keys`); they are never stored as edge properties,
  so the ingested REFERENCES edge is already aligned and this rename has no
  graph effect. Done anyway for naming consistency with the neocarta field
  names. Pure rename across the FK subpackage, `writer.py` defaults, and tests;
  isolated and easy to test.

### Property name mismatches (the biggest, most mechanical change)

- **`comment` should become `description`.** dbxcarta names the human-readable
  text field `comment` on Schema, Table, and Column. neocarta core calls it
  `description` everywhere. Rename on all three labels.
- **`data_type` should become `type`** on Column.
- **`is_nullable` should become `nullable`** on Column.
- **REFERENCES endpoint names differ.** dbxcarta uses `source_id` / `target_id`;
  neocarta core uses `source_column_id` / `target_column_id`. Align the names.

### Missing properties dbxcarta does not currently produce

- **Column primary/foreign key flags.** neocarta core has `is_primary_key` and
  `is_foreign_key` booleans on Column. dbxcarta has no equivalent today (it once
  had a `is_key_like` heuristic but removed it). **Decision: derive both from
  Unity Catalog.** `is_primary_key` comes from declared primary-key constraints;
  `is_foreign_key` comes from the columns that appear as the source of a
  REFERENCES edge (declared FKs, and inferred FKs if we choose to count them).
  These are real, populated booleans, not default-false placeholders.
- **Database descriptive fields.** neocarta core's Database has `platform`,
  `service`, and `description`. dbxcarta's Database only carries `id`, `name`,
  and bookkeeping. **Finding:** neocarta has no single fixed convention — each
  connector sets these itself (the BigQuery connector leaves both null; Dataplex
  reads them from source metadata; CSV reads them from columns). The semantics
  are: `platform` = the cloud provider (GCP / AWS / AZURE) and `service` = the
  engine (e.g. BIGQUERY); a Pydantic validator uppercases both. **Decision for
  dbxcarta:** set `service = "DATABRICKS"`, set `platform` to the workspace's
  cloud (derive from config where known, otherwise leave null — it is optional),
  and leave `description` null unless a source supplies one.

### Extra dbxcarta properties to classify as additive

dbxcarta carries several fields the core model does not mention. These do not
conflict with the core; they sit alongside it. **Decision: keep them as additive
properties now, and extend the neocarta core model later to absorb the valuable
ones** (for example `layer` on Table, and `confidence` / `source` on REFERENCES).
Until then, downstream core tooling simply ignores them:

- Table: `catalog`, `schema`, `layer` (medallion bronze/silver/gold),
  `table_type`, `created`, `last_altered`.
- Column: `catalog`, `schema`, `table`, `ordinal_position`.
- REFERENCES: `confidence` and `source` (FK provenance and score).
- All nodes: `contract_version` (dbxcarta's own versioning marker).

### Out-of-scope schema dbxcarta produces

- **Value nodes and HAS_VALUE edges.** dbxcarta writes sampled column values as
  Value nodes. In neocarta these live in the *expanded* model, not core. They
  are out of scope for this alignment but should be left working as-is, not
  removed.

### Mechanics of making the change

- Update the dbxcarta contract's per-label property lists and relationship
  property names to the new names.
- Update the DataFrame builders so the selected/renamed columns match.
- Update the embedding-text expressions and any place that references the old
  column names (for example anything reading `comment` or `data_type`).
- **IDs already match — just keep them locked.** neocarta normalizes each id
  segment as lowercase with spaces and hyphens replaced by underscores, joins
  segments with dots, and hashes Value ids as `column_id.{md5 hex}`. dbxcarta's
  `generate_id` / `generate_value_id` already do exactly this, so no id change is
  needed. The one task is to confirm the Spark-side `id_expr` produces
  byte-identical output to neocarta's `_normalize`, and ideally have both sides
  share one helper so they cannot drift.
- Update dbxcarta's tests and any golden/contract fixtures to the new names.
- Bump dbxcarta's `CONTRACT_VERSION` since this is a breaking rename.
- Update dbxcarta docs (README, contract notes) to describe the aligned schema.

## Phase 2 — Enforce the Shape with PyDeequ

Once the aligned schema is proven, this phase makes the shape a hard, checked
contract on every batch, with the neocarta Pydantic models as the single source
of truth for what "valid" means.

- **Idea.** The Pydantic core models already describe the shape: which fields
  are required, which are optional, their types, and which booleans must be
  present. We translate that shape into data-quality checks and run them, in
  Spark, over each node and relationship DataFrame right before the Neo4j write.
- **Why PyDeequ.** PyDeequ runs its checks natively as Spark jobs over the whole
  DataFrame. It does not pull rows to the driver and it is not a Python UDF, so
  it respects dbxcarta's two core rules (no driver-scale collect, no Python UDF
  for row logic). The checks become part of the same Spark plan that builds the
  batch.
- **Pydantic as the source of truth.** Rather than hand-writing checks that can
  drift from the models, we derive them from the models: a required field
  becomes a completeness (not-null) check, a typed field becomes a type check, a
  boolean becomes a membership check, the id becomes a completeness (and
  possibly uniqueness) check, and so on. One definition (the Pydantic model),
  two uses (the documented shape and the enforced shape).
- **Fail-closed.** A batch that violates the derived shape stops before it
  writes malformed nodes or edges into Neo4j, rather than silently corrupting
  the graph. The exact failure behavior (hard-fail vs quarantine) is an open
  question below.
- **Boundary.** Phase 2 enforces the *core* shape only, matching Phase 1's
  scope. It does not attempt to validate expanded concepts or anything Deequ
  cannot express (those are called out in the questions).

## Decisions (Phase 1, resolved)

- **Direction of truth for shared fields — extend core later.** For now
  dbxcarta's richer fields stay additive; the neocarta core model will be
  extended later to absorb the valuable ones.
- **ID format — already aligned, no change needed.** Both sides use the same
  recipe (lowercase, spaces/hyphens to underscores, dot-joined segments; Value
  = `column_id.{md5 hex}`). Only task: confirm the Spark `id_expr` matches
  neocarta's `_normalize` byte-for-byte, ideally by sharing one helper.
- **PK/FK flags — derive from Unity Catalog.** `is_primary_key` from declared
  PK constraints; `is_foreign_key` from REFERENCES-source columns.
- **Database `platform` / `service` — set per dbxcarta.** `service =
  "DATABRICKS"`; `platform` = the workspace cloud where known (else null);
  `description` null unless sourced. No global neocarta convention exists; each
  connector sets its own.
- **Single vs multi-catalog Database — no problem.** The core model and the MCP
  queries support many Database nodes; neocarta itself makes one Database per
  database/project. Mapping one catalog to one Database is consistent. Multi-
  catalog ingest simply produces multiple Database nodes.
- **Versioning marker — open (minor).** Keep dbxcarta's `contract_version` as
  additive bookkeeping or drop it now that the schema tracks the neocarta core.

## Outstanding Questions

### Phase 1 (schema alignment)

All blocking Phase 1 questions are resolved (see Decisions above). The only
remaining item is the minor `contract_version` keep-or-drop call.

### Phase 2 (PyDeequ enforcement)

- **Where do the neocarta Pydantic models live for dbxcarta to read?** Phase 2
  derives its checks from them. Is dbxcarta allowed to depend on the neocarta
  package, or do we need a shared, lighter schema definition both sides point
  at? (Phase 1 needs no Pydantic — names are matched by hand — so this only
  blocks Phase 2.)

- **PyDeequ on Databricks.** Is PyDeequ supported and installable on the target
  Databricks runtime, and does its required Deequ JAR match the cluster's Spark
  version? This is the first thing to confirm — it gates the whole phase.
- **Auto-derive vs hand-write the checks.** Do we introspect the Pydantic models
  to generate the Deequ checks automatically (no drift, but more upfront work),
  or hand-write a check set per label and keep it in sync manually?
- **What can Deequ actually enforce?** Not-null, type, and value-membership map
  cleanly. Harder cases need a decision: the embedding vector (an array column),
  the id format/regex, and cross-entity referential integrity (a REFERENCES edge
  pointing at a Column id that really exists). Some of these may be out of scope
  for Deequ and need a different check or none at all.
- **Failure behavior.** When a batch fails a check, do we hard-fail the whole
  run (safest, simplest), quarantine the bad rows and continue, or just warn and
  write anyway? "Fail-closed" is the stated default but the exact policy is open.
- **Where uniqueness is checked.** An id-uniqueness check is a full shuffle and
  is expensive at catalog scale. Do we enforce it per batch, once at the end, or
  rely on the Neo4j MERGE/constraint instead?
- **Performance budget.** Running a verification suite on every batch adds Spark
  work. We need to confirm the added cost is acceptable at real catalog scale,
  or scope checks down to the cheap, high-value ones.
