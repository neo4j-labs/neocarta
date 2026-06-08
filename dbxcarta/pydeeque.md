# Phase 2 — Enforce the Aligned Shape with PyDeequ, Driven by neocarta's Pydantic

## Context

Phase 1 of `align-dbxcarta.md` is complete. The graph dbxcarta writes from Unity
Catalog now has the same node labels, property names, and id format as a graph
built by a neocarta connector. Phase 1 added no validation. It only reshaped the
output.

Phase 2 makes that shape a hard, checked contract on every batch, with neocarta's
core Pydantic models as the definition of valid. Today a built DataFrame passes
through `_project()`, which checks only that the declared columns are present,
then writes straight to Neo4j. If the values are bad, for example a null `id`, a
null required boolean, or a dangling REFERENCES endpoint, they are written
malformed and silently corrupt the graph. Phase 2 closes that gap. It runs
PyDeequ checks derived from the Pydantic models over each node and relationship
DataFrame right before the Neo4j write, and fails the run when the shape is
violated.

This document proposes how the existing neocarta Pydantic models map onto PyDeequ
checks. It reflects three confirmed decisions:

1. **Source of truth.** A shared lightweight shape module, pure Pydantic with no
   pandas and no validators, that mirrors `neocarta/data_model/rdbms/core.py`,
   with a parity test guarding drift. dbxcarta does not take a runtime dependency
   on the full `neocarta` package.
2. **Derivation.** Auto-derive the Deequ checks by introspecting
   `model.model_fields`. One generic function, no hand-maintained per-label check
   list.
3. **Failure behavior.** Hard-fail, fail-closed, before the write.

Scope is the core model only: Database, Schema, Table, Column plus HAS_SCHEMA,
HAS_TABLE, HAS_COLUMN, REFERENCES. This matches Phase 1. Value nodes, HAS_VALUE,
and all expanded concepts are out of scope.

## The core idea: Pydantic field becomes a Deequ check

The neocarta models in `neocarta/data_model/rdbms/core.py` already encode the
shape. Each field carries the facts a not-null or membership check needs: its
type, whether it is Optional, and for ids and booleans its role. We read those
off `model_fields` and emit one Deequ constraint per fact.

The key derivation rule: **optionality is read from the type annotation, not from
whether a Pydantic default exists.** This matters. `nullable: bool =
Field(default=True)` is not "required" in Pydantic terms, since it has a default,
but its annotation is `bool`, not `bool | None`. In the graph it must always be
populated.

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
the boolean case, which asserts the true/false domain, and content completeness,
which catches the nulls Spark's type system permits but the graph shape forbids.

## What this looks like against the actual models

`neocarta/data_model/rdbms/core.py` yields, by the rule above:

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

The relationship Pydantic models name their fields `database_id`/`schema_id`,
`schema_id`/`table_id`, `table_id`/`column_id`, and
`source_column_id`/`target_column_id`. The DataFrames built in `schema_graph.py`
use transient join columns instead: `source_id`/`target_id` for the three
structural `HAS_*` builders, and `source_column_id`/`target_column_id` for
REFERENCES from Phase 1 sub-phase 1d. So for the structural relationships the
Pydantic field names do not match the DataFrame column names.

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

### 1. Shared lightweight shape module

Create a pure-Pydantic module in `dbxcarta-core`, which `dbxcarta-spark` already
depends on through `dbxcarta-core>=1.1.0,<2`. Place it at
`dbxcarta/dbxcarta-core/src/dbxcarta/core/shape.py`. It holds slim mirror models
with the same field names, annotations, types, and defaults as `core.py`, but
with no `field_validator`s and no `pandas` import. This keeps the cluster
footprint to just `pydantic` and avoids a runtime dependency on the full
`neocarta` wheel.

Putting it in `dbxcarta-core` rather than `dbxcarta-spark` means the models carry
no Spark or PyDeequ import, so they stay importable anywhere and unit-testable
without a SparkSession.

### 2. Drift guard: a parity test

We are not changing `core.py`, which is a stated constraint of the alignment, so
the shared module cannot be the literal object `core.py` imports. We guard drift
with a test in dbxcarta's test suite, which may dev-depend on `neocarta`. For each
core label, assert that `shape.<Model>.model_fields` matches
`neocarta.data_model.rdbms.core.<Model>.model_fields` on field names, optionality,
and base type. If someone changes `core.py`, this test goes red until the shared
module is updated. That makes the shared module a faithful mirror rather than a
copy that can rot.

### 3. Auto-derivation function

A single function turns any shape model into Deequ constraints:

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

A thin dispatch maps each `NodeLabel` and `RelType` to its shape model, and for
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
failures is driver-safe. It does not violate the no-catalog-scale-collect rule.
The row scan runs as a Spark job, and no Python UDF is introduced.

### 4. Insertion point: a single chokepoint

`run.py`'s `_project(df, label)` at roughly lines 651 to 674 is already the
fail-closed column boundary. Phase 2's value check is its data-level counterpart
and slots in right after it, before the write.

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

No change to `writer.py` or `neo4j_io.py` is needed. The verification is upstream
of the Spark connector `.write.format(...)` call.

## What Deequ enforces, and the deliberate non-goals

Enforced. These are cheap single-pass aggregations, combined into one Spark job
per suite:

- Required-field completeness, the bulk of the value.
- Boolean domain on `nullable`, `is_primary_key`, `is_foreign_key`.
- Optional and opt-in: id-format regex through `hasPattern(id, NORMALIZED_ID_REGEX)`.
  Phase 1 already guarantees the format through the shared id helper, so this is a
  belt-and-suspenders single-pass check, not load-bearing.

Deliberately not enforced per batch:

- **id uniqueness.** `isUnique` is a full shuffle and expensive at catalog scale.
  The Neo4j write already uses MERGE with `node.keys=id`, so duplicate ids across
  batches merge rather than duplicate. Uniqueness in the graph is guaranteed by
  the write, which makes a per-batch Deequ uniqueness check redundant for
  correctness. Recommendation: rely on MERGE, and optionally add a single
  end-of-run distinct-count check if we want an explicit signal.
- **REFERENCES referential integrity**, meaning the endpoint Column id actually
  exists. Deequ cannot express a cross-DataFrame join as a constraint cheaply. The
  writer already sets `relationship.source/target.save.mode = Match`, so a
  REFERENCES edge whose endpoint node does not exist is simply not created.
  Dangling edges cannot enter the graph. Recommendation: rely on the writer's
  Match semantics, and if we want a pre-write signal, add an optional anti-join
  count, not a Deequ constraint, that fails when more than zero endpoints are
  missing.
- **embedding array contents.** It is an array column, Deequ has no good
  constraint for it, and the field is Optional. Skipped.

## Files to create and modify

Create:

- `dbxcarta/dbxcarta-core/src/dbxcarta/core/shape.py`. Slim pure-Pydantic mirror
  of the four core nodes and four core relationships.
- `dbxcarta/dbxcarta-spark/src/dbxcarta/spark/ingest/load/shape_checks.py`, name
  to be confirmed. Holds `add_model_checks`, `verify_shape`, the `NodeLabel` and
  `RelType` to model dispatch, the relationship `field_to_col` maps,
  `ShapeViolation`, and the optional `NORMALIZED_ID_REGEX`.

Modify:

- `dbxcarta/dbxcarta-spark/.../ingest/run.py`. Call `verify_shape` after
  `_project` in `_write_label_nodes()`, and after the rel build in `_load()`.
- `dbxcarta/dbxcarta-spark/pyproject.toml`. Add the `pydeequ` dependency.
- Submit and cluster config. Add the Deequ Maven JAR, see gating below.
- `dbxcarta/CHANGELOG.md`, contract notes, and README. Note Phase 2 enforcement.
- New tests. A parity test of shape against `core.py`; unit tests for
  `add_model_checks` that assert the right constraints per model; and an
  integration test that a null-`id` or null-boolean batch hard-fails before write.

No change to `core.py`, to the `contract.py` property lists, or to the builders in
`schema_graph.py`.

## Gating prerequisite: confirm first

PyDeequ plus the Deequ JAR on the target Databricks runtime gates the whole phase
and must be verified before any code is written:

- dbxcarta targets `pyspark>=3.5`. Confirm the cluster's exact Spark and DBR
  version, then install the matching Deequ Maven JAR, for example
  `com.amazon.deequ:deequ:<ver>-spark-3.5`, on the submit cluster, excluding
  `net.sourceforge.f2j:arpack_combined_all`.
- `pip install pydeequ` on the cluster, and set the `SPARK_VERSION` env var before
  the first `import pydeequ`. PyDeequ reads it to pick the JAR coordinate.
- PyDeequ historically lagged Spark support, see awslabs/python-deequ issue 192.
  Spark 3.5 is supported now, but the JAR-to-runtime match is the classic failure
  point. Verify a trivial `VerificationSuite(...).run()` succeeds on the actual
  cluster before building the derivation layer.

## Verification

1. **Gating smoke test**, above. A trivial Deequ suite runs green on the target
   cluster.
2. **Unit, no Spark.** `add_model_checks` against each shape model produces exactly
   the expected constraints: Column gives completeness on id and name plus three
   booleans with Boolean type; Database gives id and name only; References gives
   both endpoint cols. The parity test confirms the shape module matches `core.py`
   `model_fields`.
3. **Integration**, `make test-it` and `make test-mcp`, Docker. Run the pipeline
   against a known-good catalog. All suites pass and the graph loads. Then inject a
   violation by forcing a null `id` or null `is_primary_key` into a built
   DataFrame, and assert the run hard-fails before the Neo4j write, leaving the
   graph unchanged.
4. **Performance check at scale.** Confirm the per-chunk suite cost, a few extra
   single-pass aggregations, is acceptable on a real catalog, and confirm no
   `isUnique` shuffle slipped into the per-batch path.

## Residual open items

- id-format regex as an enforced check: include opt-in, or leave it to Phase 1's
  shared helper? Recommendation: opt-in, off by default.
- End-of-run uniqueness signal: add a single distinct-count check, or trust MERGE
  entirely? Recommendation: trust MERGE for v1.
- REFERENCES referential-integrity anti-join signal: add the pre-write count, or
  trust the writer's Match mode? Recommendation: trust Match for v1.
- `contract_version` and other additive dbxcarta-only properties are not in the
  core models, so the introspection ignores them. This is consistent with enforce
  the core shape only.
