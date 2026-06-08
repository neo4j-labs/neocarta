# Phase 2 — Enforce the Aligned Shape with PyDeequ, Driven by One Shared Schema

## Context

Phase 1 of `align-dbxcarta.md` is done. The graph dbxcarta writes from Unity
Catalog now has the same node labels, property names, and id format as a graph
built by a neocarta connector. Phase 1 added no validation. It only reshaped the
output.

Phase 2 turns that shape into a hard, checked contract on every batch. The
Pydantic models are the definition of valid. Today a built DataFrame passes
through `_project()`, which checks only that the declared columns are present,
then writes straight to Neo4j. If a value is bad, for example a null `id`, a null
required boolean, or a dangling REFERENCES endpoint, it is written malformed and
quietly corrupts the graph. Phase 2 closes that gap. It runs PyDeequ checks
derived from the Pydantic models over each node and relationship DataFrame right
before the Neo4j write, and it fails the run when the shape is violated.

This document proposes how the Pydantic models map onto PyDeequ checks, and the
package change that makes those models a true single source of truth.

## Fixed decisions

These are decided. They are not options to revisit. The point is to stop papering
over the seam between neocarta and dbxcarta and make one clean cut.

1. **One shared schema package.** The core Pydantic models move into a new small
   package, called `carta-schema` here, that both neocarta and dbxcarta depend on.
   There is one definition of the models, in one place.
2. **We are changing `core.py`.** `core.py` no longer lives inside neocarta. It
   moves into the shared package. This is a complete move, not a wrapper around
   the old location. Every place that imported the old path is updated to import
   the new one.
3. **No shims, no re-exports, no compatibility layers.** This is a hard cutover.
   We do not leave a forwarding stub at the old `neocarta/data_model/rdbms/core.py`
   path. We do not keep a mirror copy. We do not add a parity test to compare two
   copies, because there is only one copy.
4. **pandas stays in the shared package.** The models keep their validators,
   including the `from pandas import isna` NaN-to-None casting. pandas is a
   required dependency of `carta-schema`. pandas is already on the Databricks
   runtime, so this adds no real weight on the cluster, and it keeps neocarta's
   behavior identical to today.
5. **Auto-derive the Deequ checks** by reading `model.model_fields`. One generic
   function, no hand-maintained per-label check list.
6. **Hard-fail, fail-closed, before the write.**

Scope is the core model only: Database, Schema, Table, Column plus HAS_SCHEMA,
HAS_TABLE, HAS_COLUMN, REFERENCES. This matches Phase 1. Value nodes, HAS_VALUE,
and all expanded concepts are out of scope.

## The package shape, and why it beats a mirror

```
        ┌───────────────────────────┐
        │   carta-schema  (new)     │   small package: the core
        │   core.py lives here      │   Pydantic models + pandas,
        │   one definition          │   nothing else
        └─────────────┬─────────────┘
                      │  both depend on it
          ┌───────────┴───────────┐
          ▼                       ▼
    ┌───────────┐           ┌──────────────┐
    │ neocarta  │           │ dbxcarta-core│
    └───────────┘           └──────┬───────┘
                                   ▼
                            ┌──────────────┐
                            │ dbxcarta-spark│
                            └──────────────┘
```

A mirror copy plus a drift test was the timid version. It keeps two files and
adds a test whose only job is to notice when the two files disagree. The shared
package removes the second file. There is nothing to drift, so there is nothing to
test for drift. If you change the schema, you change it once, and both projects
see the change.

This is a permanent monorepo. dbxcarta is a normal directory in this repo, not a
git subtree, so a cross-package dependency inside the repo is fine. There is no
"split it out later" constraint to protect, so the cleanest dependency graph wins.

### Why we do not just depend on neocarta directly

The obvious shortcut would be for dbxcarta to depend on `neocarta` and import the
models from there. We reject that. `neocarta` is a heavy package. It pulls in the
source connectors, which bring BigQuery, Pinecone, Dataplex, and their client
libraries. dbxcarta runs on a Databricks cluster and only needs the field
definitions. Shipping the entire connector stack to the cluster to read a handful
of Pydantic field names is wasteful and fragile.

The shared package fixes both problems at once. `carta-schema` is tiny: Pydantic
plus pandas, and pandas is already on the cluster. dbxcarta depends on something
small. neocarta depends on the same small thing. One source of truth, and a light
cluster footprint, with no tradeoff between them.

## The core idea: a Pydantic field becomes a Deequ check

Each field on a core model carries the facts a check needs: its type, whether it
is Optional, and for ids and booleans its role. We read those off `model_fields`
and emit one Deequ constraint per fact.

The key rule: **read optionality from the type annotation, not from whether a
Pydantic default exists.** This matters. `nullable: bool = Field(default=True)` is
not "required" in Pydantic terms, because it has a default, but its annotation is
`bool`, not `bool | None`. In the graph it must always be filled in.

```
                         ┌───────────────────────────────────────┐
                         │     Pydantic field on a core model     │
                         │   e.g.  nullable: bool = Field(...)     │
                         └────────────────────┬──────────────────-┘
                                              │
                         read the TYPE ANNOTATION, not the default
                                              │
                ┌─────────────────────────────┼─────────────────────────────┐
                │                             │                             │
       annotation has no None        annotation is a bool          annotation has None
       (id, name, *_id, bool)        (nullable, is_*_key)          (description, type,
                │                             │                     criteria, embedding)
                ▼                             ▼                             ▼
        ┌───────────────┐          ┌──────────────────────┐        ┌───────────────┐
        │ isComplete(c) │          │ hasDataType(c,       │        │  no check     │
        │  not-null     │          │   Boolean)           │        │  nullable by  │
        └───────────────┘          │  + isComplete(c)     │        │  design       │
                                   └──────────────────────┘        └───────────────┘
```

The derivation table, applied per field:

| Pydantic field annotation       | Example fields                                  | Deequ constraint                                   |
|----------------------------------|-------------------------------------------------|----------------------------------------------------|
| Non-Optional `str`               | `id`, `name`, all `*_id`                        | `isComplete(col)`                                  |
| `id` specifically                | `id`                                            | `isComplete(col)`. Uniqueness handled by Neo4j MERGE |
| Non-Optional `bool`              | `nullable`, `is_primary_key`, `is_foreign_key`  | `isComplete(col)` + `hasDataType(col, Boolean)`    |
| Optional `str`, `str \| None`    | `description`, `type`, `criteria`, `platform`   | none, nullable by design                           |
| `list[float] \| None`            | `embedding`                                     | none. Array column, and Optional                   |

Spark already enforces column type through the builders' explicit `StructType`
and through `_project()`. So `hasDataType` adds little for strings. Its value is
the boolean case, which pins the true and false domain, and content completeness,
which catches the nulls Spark's type system allows but the graph shape forbids.

## What this produces for the real models

```
 Database ──► isComplete(id), isComplete(name)
              platform, service, description, embedding  →  Optional, skipped

 Schema   ──► isComplete(id), isComplete(name)
              description, embedding  →  Optional, skipped

 Table    ──► isComplete(id), isComplete(name)
              description, embedding  →  Optional, skipped

 Column   ──► isComplete(id), isComplete(name)
              isComplete(nullable)        + hasDataType(nullable, Boolean)
              isComplete(is_primary_key)  + hasDataType(is_primary_key, Boolean)
              isComplete(is_foreign_key)  + hasDataType(is_foreign_key, Boolean)
              type, description, embedding  →  Optional, skipped

 HasSchema / HasTable / HasColumn ──► isComplete on each endpoint id
 References                        ──► isComplete(source_column_id),
                                       isComplete(target_column_id)
                                       criteria  →  Optional, skipped
```

### The relationship name wrinkle

The relationship models name their fields `database_id`/`schema_id`,
`schema_id`/`table_id`, `table_id`/`column_id`, and
`source_column_id`/`target_column_id`. The DataFrames built in `schema_graph.py`
use transient join columns instead: `source_id`/`target_id` for the three
structural `HAS_*` builders, and `source_column_id`/`target_column_id` for
REFERENCES. So for the structural relationships the field names do not match the
DataFrame column names.

The derivation needs a small per-`RelType` field-to-column map so the
required-endpoint checks land on the real transient columns:

```
   Pydantic model field          field_to_col map          DataFrame column
   ───────────────────────       ────────────────          ────────────────
   HasSchema.database_id   ─────────────────────────────►   source_id
   HasSchema.schema_id     ─────────────────────────────►   target_id
   HasTable.schema_id      ─────────────────────────────►   source_id
   HasTable.table_id       ─────────────────────────────►   target_id
   HasColumn.table_id      ─────────────────────────────►   source_id
   HasColumn.column_id     ─────────────────────────────►   target_id

   References.source_column_id ─── identity, no remap ───►   source_column_id
   References.target_column_id ─── identity, no remap ───►   target_column_id
```

This map lives next to the check builder and is the one place that knows the
transient-column convention.

## Architecture

### 1. The shared schema package

Create `carta-schema`, a new package in this monorepo. Move the core models into
it from `neocarta/data_model/rdbms/core.py`. The models keep their fields,
annotations, validators, and the pandas import exactly as they are today. pandas
is a required dependency of `carta-schema`.

Both neocarta and `dbxcarta-core` declare `carta-schema` as a dependency.
`dbxcarta-spark` gets it through `dbxcarta-core`, which it already depends on.

### 2. Update every caller, with no shim

Every import of the old path is changed to the new package. For example:

```python
# before
from neocarta.data_model.rdbms.core import Column, Database, References

# after
from carta_schema.rdbms.core import Column, Database, References
```

We do not leave a re-export at the old location. The old path is gone. A search
for the old import string across the repo should return zero hits when the cutover
is complete. This is the hard cutover. If a caller is missed, it fails loudly at
import time, which is exactly what we want.

### 3. Auto-derivation function

One function turns any model into Deequ constraints:

```python
import typing
from pydantic import BaseModel
from pydeequ.checks import Check, ConstrainableDataTypes


def _is_optional(annotation) -> bool:
    return type(None) in typing.get_args(annotation)


def _base_type(annotation):
    args = [a for a in typing.get_args(annotation) if a is not type(None)]
    return args[0] if args else annotation


def add_model_checks(
    check: Check,
    model: type[BaseModel],
    field_to_col: dict[str, str] | None = None,
) -> Check:
    field_to_col = field_to_col or {}
    for name, field in model.model_fields.items():
        col = field_to_col.get(name, name)
        ann = field.annotation
        base = _base_type(ann)
        if base is list:  # embedding, an array, skip
            continue
        if not _is_optional(ann):  # non-Optional annotation must be non-null
            check = check.isComplete(col)
        if base is bool:
            check = check.hasDataType(col, ConstrainableDataTypes.Boolean)
    return check
```

A thin dispatch maps each `NodeLabel` and `RelType` to its model, and for
relationships its `field_to_col` map, then builds and runs the suite:

```python
from pydeequ.checks import Check, CheckLevel
from pydeequ.verification import VerificationSuite, VerificationResult


def verify_shape(spark, df, label_name, model, field_to_col=None) -> None:
    check = add_model_checks(
        Check(spark, CheckLevel.Error, f"{label_name} shape"),
        model,
        field_to_col,
    )
    result = VerificationSuite(spark).onData(df).addCheck(check).run()
    if result.status != "Success":
        bad = VerificationResult.checkResultsAsDataFrame(spark, result)
        failed = [r for r in bad.collect() if r["constraint_status"] != "Success"]
        raise ShapeViolation(f"{label_name} failed shape checks: {failed}")
```

`checkResultsAsDataFrame` returns one row per constraint, so the `.collect()` of
failures is driver-safe. It does not break the no-catalog-scale-collect rule. The
row scan runs as a Spark job, and no Python UDF is introduced.

### 4. Where the check runs

`run.py`'s `_project(df, label)` at roughly lines 651 to 674 is already the
fail-closed column boundary. The value check is its data-level partner and runs
right after it, before the write.

```
   build DataFrame
   (schema_graph.py)
          │
          ▼
   ┌──────────────┐     columns present?      ┌──────────────────┐
   │  _project()  │ ────────────────────────► │  verify_shape()  │
   │  column      │                           │  values valid?   │
   │  boundary    │                           │  Deequ suite     │
   └──────────────┘                           └────────┬─────────┘
                                                 pass   │   fail
                                            ┌───────────┴───────────┐
                                            ▼                       ▼
                                   ┌──────────────────┐   ┌──────────────────┐
                                   │ write_node /     │   │ raise            │
                                   │ write_rel        │   │ ShapeViolation   │
                                   │ Neo4j connector  │   │ run stops, graph │
                                   │                  │   │ untouched        │
                                   └──────────────────┘   └──────────────────┘
```

- **Nodes.** Inside `_write_label_nodes()` at roughly run.py lines 412 to 444:
  after `_project(..., label)`, call `verify_shape(...)`, then `write_node(...)`.
  Table and Column nodes are chunked, so this runs per chunk.
- **Relationships.** Inside `_load()` at roughly run.py lines 560 to 649: after
  the rel DataFrame is built and partitioned, call `verify_shape(...)` with the
  RelType's `field_to_col` map, then `write_rel(...)`.

No change to `writer.py` or `neo4j_io.py` is needed. The check sits upstream of
the Spark connector `.write.format(...)` call.

## What Deequ enforces, and what it does not

Enforced. These are cheap single-pass aggregations, combined into one Spark job
per suite:

- Required-field completeness. This is the bulk of the value.
- Boolean domain on `nullable`, `is_primary_key`, `is_foreign_key`.
- Optional and opt-in: id-format regex through `hasPattern(id, NORMALIZED_ID_REGEX)`.
  Phase 1 already guarantees the format through the shared id helper, so this is a
  belt-and-suspenders single-pass check, not load-bearing.

Not enforced per batch, on purpose:

- **id uniqueness.** `isUnique` is a full shuffle and expensive at catalog scale.
  The Neo4j write already uses MERGE with `node.keys=id`, so duplicate ids across
  batches merge rather than duplicate. The write guarantees uniqueness in the
  graph, so a per-batch Deequ uniqueness check is redundant. Rely on MERGE, and
  optionally add a single end-of-run distinct-count check if we want a signal.
- **REFERENCES referential integrity**, meaning the endpoint Column id really
  exists. Deequ cannot express a cross-DataFrame join as a constraint cheaply. The
  writer already sets `relationship.source/target.save.mode = Match`, so a
  REFERENCES edge whose endpoint node does not exist is simply not created.
  Dangling edges cannot enter the graph. Rely on Match, and if we want a pre-write
  signal, add an optional anti-join count, not a Deequ constraint, that fails when
  more than zero endpoints are missing.
- **embedding array contents.** It is an array column, Deequ has no good
  constraint for it, and the field is Optional. Skipped.

## Files to create and modify

Create:

- `carta-schema` package. Move the core models into it. pandas is a required
  dependency. Suggested module path `carta_schema/rdbms/core.py`.
- `dbxcarta/dbxcarta-spark/src/dbxcarta/spark/ingest/load/shape_checks.py`, name
  to be confirmed. Holds `add_model_checks`, `verify_shape`, the `NodeLabel` and
  `RelType` to model dispatch, the relationship `field_to_col` maps,
  `ShapeViolation`, and the optional `NORMALIZED_ID_REGEX`.

Modify:

- Delete `neocarta/data_model/rdbms/core.py` at its old location. No shim.
- Every neocarta import of the old path. Repoint to `carta_schema`. A search for
  the old import string must return zero hits.
- `neocarta` and `dbxcarta-core` `pyproject.toml`. Add the `carta-schema`
  dependency.
- `dbxcarta/dbxcarta-spark/pyproject.toml`. Add the `pydeequ` dependency.
- `dbxcarta/dbxcarta-spark/.../ingest/run.py`. Call `verify_shape` after
  `_project` in `_write_label_nodes()`, and after the rel build in `_load()`.
- Submit and cluster config. Add the Deequ Maven JAR, see gating below.
- `dbxcarta/CHANGELOG.md`, neocarta `CHANGELOG.md`, contract notes, and READMEs.
  Record the package move and the Phase 2 enforcement.
- New tests. Unit tests for `add_model_checks` that assert the right constraints
  per model, and an integration test that a null-`id` or null-boolean batch
  hard-fails before write. There is no parity test, because there is one copy of
  the models.

No change to the `contract.py` property lists or to the builders in
`schema_graph.py`. The models keep the same fields and validators. They only
change location.

## Gating prerequisite: confirm first

PyDeequ plus the Deequ JAR on the target Databricks runtime gates the whole phase.
Confirm it before writing the check code:

- dbxcarta targets `pyspark>=3.5`. Confirm the cluster's exact Spark and DBR
  version, then install the matching Deequ Maven JAR, for example
  `com.amazon.deequ:deequ:<ver>-spark-3.5`, on the submit cluster, excluding
  `net.sourceforge.f2j:arpack_combined_all`.
- `pip install pydeequ` on the cluster, and set the `SPARK_VERSION` env var before
  the first `import pydeequ`. PyDeequ reads it to pick the JAR coordinate.
- PyDeequ has lagged Spark support in the past, see awslabs/python-deequ issue 192.
  Spark 3.5 is supported now, but the JAR-to-runtime match is the classic failure
  point. Verify a trivial `VerificationSuite(...).run()` succeeds on the actual
  cluster before building the derivation layer.

## Verification

1. **Package cutover.** A repo-wide search for the old import path returns zero
   hits. neocarta and dbxcarta both build and import `carta_schema`. The full
   neocarta test suite passes unchanged, which proves the move did not alter
   behavior.
2. **Gating smoke test.** A trivial Deequ suite runs green on the target cluster.
3. **Unit, no Spark.** `add_model_checks` against each model produces exactly the
   expected constraints: Column gives completeness on id and name plus three
   booleans with Boolean type, Database gives id and name only, References gives
   both endpoint columns.
4. **Integration**, `make test-it` and `make test-mcp`, Docker. Run the pipeline
   against a known-good catalog. All suites pass and the graph loads. Then inject a
   violation by forcing a null `id` or null `is_primary_key` into a built
   DataFrame, and confirm the run hard-fails before the Neo4j write and leaves the
   graph unchanged.
5. **Performance check at scale.** Confirm the per-chunk suite cost, a few extra
   single-pass aggregations, is acceptable on a real catalog, and confirm no
   `isUnique` shuffle slipped into the per-batch path.

## Residual open items

- id-format regex as an enforced check: include it opt-in, or leave it to Phase
  1's shared helper? Recommendation: opt-in, off by default.
- End-of-run uniqueness signal: add a single distinct-count check, or trust MERGE
  entirely? Recommendation: trust MERGE for v1.
- REFERENCES referential-integrity anti-join signal: add the pre-write count, or
  trust the writer's Match mode? Recommendation: trust Match for v1.
- `contract_version` and other additive dbxcarta-only properties are not in the
  core models, so the introspection ignores them. This matches enforce the core
  shape only.
