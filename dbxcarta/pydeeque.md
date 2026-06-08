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
models from there. We reject that, and the reason is in neocarta's own
`pyproject.toml`. neocarta's required dependencies, the ones every install pulls
whether you want them or not, are:

```
google-cloud-bigquery[pandas], google-cloud-bigquery-storage,
google-cloud-dataplex, litellm, openai, neo4j, sqlglot,
pydantic, pandas, python-dotenv
```

These are hard dependencies, not optional extras. So `pip install neocarta`
drags the entire BigQuery, Dataplex, and LLM client stack onto the machine. On a
Databricks cluster that only needs to read a handful of Pydantic field names,
shipping all of that is wasteful and fragile.

The shared package fixes this. `carta-schema` is tiny: Pydantic plus pandas, and
pandas is already on the cluster. dbxcarta depends on something small. neocarta
depends on the same small thing. One source of truth, and a light cluster
footprint, with no tradeoff between them.

### Could it live in `neocarta/core` instead, with a toml update?

Short answer: not cleanly, and not with only a toml update.

The problem is the dependency list above. If the models lived in a `neocarta/core`
folder, then for dbxcarta to import them it would still have to
`pip install neocarta`, which pulls the whole BigQuery and Dataplex and LLM
stack onto the cluster. Moving the models to a `core` subfolder does not change
what `pip install neocarta` brings down. The heavy dependencies are declared at
the package level, not at the folder level.

To make `neocarta/core` work as a light shared base, you would have to demote all
of those connector libraries to optional extras, so that a bare
`pip install neocarta` resolves to just pydantic and pandas, and the connectors
only arrive with `pip install neocarta[bigquery]` and similar. That is a large,
risky change to neocarta's dependency model. Every existing consumer that assumes
the connectors are present on a plain install would break.

So `neocarta/core` is possible only as the end state of a much bigger refactor.
The standalone `carta-schema` package reaches the same goal, one shared
definition with a light footprint, without touching how neocarta ships its
connectors. That is why the decision is a standalone package, not `neocarta/core`.

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

### Is this manual or automated? It is automated.

Nobody writes `isComplete("id")` by hand. A loop reads the model and writes the
checks for you.

Think of a Pydantic model as a form that lists every field and its rules. The
code reads that form one line at a time. For each field it asks two yes-or-no
questions:

1. Can this field be empty? That is, does its type allow `None`? If no, add a
   must-not-be-null check.
2. Is this a true-or-false field? That is, is its type `bool`? If yes, add a
   must-be-a-real-boolean check.

That is the whole rule. The loop visits every field and stacks up the checks it
finds. The `add_model_checks` function shown later is exactly this loop. You feed
it a model, it hands back a Deequ check with one constraint per answered question.

Here is the loop running over the `Column` model, field by field:

```
   Column field             question the loop asks          check it adds
   ──────────────────────   ────────────────────────────    ─────────────────────────
   id: str                  empty allowed? no               isComplete(id)
   name: str                empty allowed? no               isComplete(name)
   description: str | None  empty allowed? yes              (nothing)
   embedding: list | None   is it a list? yes, skip         (nothing)
   type: str | None         empty allowed? yes              (nothing)
   nullable: bool           empty allowed? no + bool?       isComplete + Boolean type
   is_primary_key: bool     empty allowed? no + bool?       isComplete + Boolean type
   is_foreign_key: bool     empty allowed? no + bool?       isComplete + Boolean type
```

Result for `Column`: five not-null checks and three boolean-type checks, all
generated, none typed out by a person.

Why automated and not a hand-written checks file? A hand-written file is a second
copy of the schema. The day someone adds a field to the model and forgets to add
its check, the file is wrong and nothing tells you. The loop cannot forget. It
reads whatever fields the model has today. Add a field, the loop checks it on the
next run. Remove a field, its check disappears. The model stays the only thing you
edit, which is the whole point of one shared schema.

### Can it check field types besides bool?

Yes. The boolean case is just the one type lookup the current core models happen
to need. Deequ's `hasDataType` accepts a small set of types: `String`,
`Integral`, `Fractional`, `Numeric`, `Boolean`, and `Null`. The loop maps a
Python type to one of these. Today it has one entry, `bool` to `Boolean`, because
that is the only non-string scalar in the core models. Adding more types is one
more line each in a lookup table, not a rewrite:

```
   Python type on the field        Deequ type check
   ─────────────────────────       ──────────────────────────────
   bool                            hasDataType(col, Boolean)   ← today
   int                             hasDataType(col, Integral)
   float                           hasDataType(col, Fractional)
   str                             hasDataType(col, String)    ← see note
```

Two honest caveats on what is worth turning on now:

- **String type checks add little.** The DataFrames already arrive with an
  explicit Spark `StructType`, so a column declared as a string is already a
  string. A Deequ `String` check would only restate what Spark already enforces.
  The valuable string checks are about content, not type, for example the
  id-format regex.
- **There are no `int` or `float` scalars in the core models today.** The only
  numeric field is `embedding`, which is a `list[float]` we skip. So an `int` or
  `float` entry would be dead code until the core model grows. The point of
  adding it to the lookup is that the day the core model gains, say, a numeric
  `confidence` on REFERENCES, the check appears automatically with no new code.

The same idea extends past plain types to richer constraints, each driven by what
the Pydantic field already declares:

- A field typed as a `Literal` or an `Enum`, for example a fixed set of medallion
  layers or a `service` that must be `DATABRICKS`, maps to
  `isContainedIn(col, [allowed values])`. The allowed values come straight from
  the annotation.
- A numeric field with a known floor, for example an `ordinal_position` that must
  be zero or greater, maps to `isNonNegative(col)`, and a bounded score maps to
  `hasMin` and `hasMax`.

For v1 the recommendation is to keep the loop to the two checks the core models
actually need, not-null and boolean type, and to leave the type lookup and the
Literal-to-membership rule in place as the obvious extension points. The
architecture is built so that enriching the checks is adding entries to a table,
never editing a per-label list by hand.

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

Yes, it is a new top-level folder, the same kind of thing as the existing
`dbxcarta-core` package. This repo is a `uv` workspace, and every package is a
folder with its own `pyproject.toml` and a `src/` tree. `carta-schema` is one
more workspace member, sitting at the repo root next to `neocarta/` and
`dbxcarta/`:

```
neocarta/                            repo root (the git repo)
├── neocarta/                        existing package folder, the heavy package
├── dbxcarta/                        existing, the Databricks packages
│   ├── dbxcarta-core/
│   └── dbxcarta-spark/
└── carta-schema/                    NEW top-level workspace member
    ├── pyproject.toml               name = "carta-schema"; deps: pydantic, pandas
    └── src/
        └── carta_schema/
            ├── __init__.py
            ├── py.typed
            └── rdbms/
                ├── __init__.py
                └── core.py          the models, moved here verbatim
```

The import path becomes `from carta_schema.rdbms.core import Column`. It keeps the
same `rdbms/core.py` sub-path the models have today, so the only thing that
changes in an import line is the package prefix.

Three small edits wire it in:

1. Add `"carta-schema"` to `[tool.uv.workspace] members` in the root
   `pyproject.toml`.
2. Add `carta-schema` to neocarta's `dependencies` in the root `pyproject.toml`.
3. Add `carta-schema` to `dbxcarta-core`'s `dependencies` in
   `dbxcarta/dbxcarta-core/pyproject.toml`. `dbxcarta-spark` gets it for free,
   because it already depends on `dbxcarta-core`.

Move the core models into the new package from
`neocarta/data_model/rdbms/core.py`. They keep their fields, annotations,
validators, and the pandas import exactly as they are today. pandas is a required
dependency of `carta-schema`.

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
        raise ShapeViolationError(f"{label_name} failed shape checks: {failed}")
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
                                   ┌──────────────────┐   ┌─────────────────────┐
                                   │ write_node /     │   │ raise               │
                                   │ write_rel        │   │ ShapeViolationError │
                                   │ Neo4j connector  │   │ run stops, graph    │
                                   │                  │   │ untouched           │
                                   └──────────────────┘   └─────────────────────┘
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
  `ShapeViolationError`, and the optional `NORMALIZED_ID_REGEX`.

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

## Phased implementation plan

Three phases, in order. Each one is shippable on its own. Because neocarta's
cutover is last, neocarta keeps using its own current `core.py` through phases 1
and 2. That is a short, deliberate migration window, not a permanent mirror.
Phase 3 deletes the old copy, so the finished state has one definition and no
shim.

**Status: Phase 1 done. Phase 2 check derivation done (not yet wired into the
Spark pipeline). Phase 3 not started.**

### Phase 1 — Build `carta-schema` (DONE)

Stand up the shared package on its own. Touch nothing in neocarta or dbxcarta yet.

- [x] Create the `carta-schema/` folder at the repo root with a `pyproject.toml`,
      `name = "carta-schema"`, dependencies `pydantic` and `pandas`. Uses the
      `uv_build` backend with `module-name = "carta_schema"`, matching
      `dbxcarta-core`.
- [x] Add the eight core models to `src/carta_schema/rdbms/core.py`: Database,
      Schema, Table, Column, HasSchema, HasTable, HasColumn, References. Copied
      verbatim from neocarta, validators and pandas import intact.
- [x] Add `src/carta_schema/__init__.py`, `rdbms/__init__.py`, and `py.typed`.
- [x] Add `"carta-schema"` to `[tool.uv.workspace] members` and a
      `carta-schema = { workspace = true }` entry under `[tool.uv.sources]` in the
      root `pyproject.toml`. Added a `carta-schema/tests/**` entry to ruff
      `per-file-ignores` so the tests get the same leniency as the root `tests/`
      dir.
- [x] Ran `uv sync` and confirmed `from carta_schema.rdbms.core import Column`
      imports.
- [x] Added `carta-schema/tests/test_core.py`. Five tests pass with
      `uv run --package carta-schema pytest carta-schema/tests/`. `ruff format`
      and `ruff check` are clean.

Nothing in neocarta or dbxcarta was touched. neocarta still uses its own
`neocarta/data_model/rdbms/core.py`, which is correct for this phase.

### Phase 2 — Make dbxcarta use it, and add PyDeequ enforcement

dbxcarta is the first consumer of the new package, and the place the checks run.
The check-derivation half is done. The pipeline-wiring half is not, and is
deliberately held back so the derived checks can be reviewed before they gate
real writes.

Done (check derivation, no pipeline changes):

- [x] Added `carta-schema` to `dbxcarta-core`'s dependencies. `dbxcarta-spark`
      gets it through `dbxcarta-core`.
- [x] Created
      `dbxcarta-spark/src/dbxcarta/spark/ingest/load/shape_checks.py` with the
      pure `derive_constraints` (the Pydantic-to-check mapping), `resolve`, the
      `NodeLabel` and `RelType` to model dispatch, the relationship `field_to_col`
      maps, `add_model_checks`, `verify_shape`, and `ShapeViolationError`. Imports
      the models from `carta_schema`. `pydeequ` is imported lazily so the module
      loads without it.
- [x] Added `dbxcarta/tests/spark/shape_checks/test_shape_checks.py`. Nine
      Spark-free tests pin the derived constraints per model and the apply layer
      (via a fake Check); one live `verify_shape` test is gated on PyDeequ and
      skips locally. `ruff` and `mypy -p dbxcarta.spark` are clean. A
      `[[tool.mypy.overrides]]` entry treats `pydeequ.*` as untyped.

Not done (pipeline wiring, gated on the prerequisite below):

- [ ] Confirm the gating prerequisite below: PyDeequ and the Deequ JAR run on the
      target Databricks cluster. Local dev has Spark 4.1, which has no matching
      Deequ JAR, so the live run cannot be proven here.
- [ ] Add `pydeequ` to `dbxcarta-spark`'s dependencies, and add the Deequ Maven
      JAR to the cluster and submit config.
- [ ] Call `verify_shape` in `run.py`: after `_project` in `_write_label_nodes()`,
      and after the rel build in `_load()`.
- [ ] Run the gated live test (and an integration test) on a cluster: a clean
      catalog passes, and an injected null `id` or null boolean hard-fails before
      the Neo4j write.
- [ ] Decide and, if chosen, add the optional `NORMALIZED_ID_REGEX` id check.
- [ ] Update `dbxcarta/CHANGELOG.md` and the contract and README notes.

### Phase 3 — Cut neocarta over and retire the old copy

The final cut. After this there is one definition and the old path is gone.

- [ ] Add `carta-schema` to neocarta's dependencies in the root `pyproject.toml`.
- [ ] Repoint every neocarta import from `neocarta.data_model.rdbms.core` to
      `carta_schema.rdbms.core`.
- [ ] Delete `neocarta/data_model/rdbms/core.py`. No shim, no re-export.
- [ ] Grep the repo for the old import path. Expect zero hits.
- [ ] Run the full neocarta test suite. It must pass unchanged, which proves the
      move did not alter behavior.
- [ ] Update neocarta's `CHANGELOG.md`.

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
