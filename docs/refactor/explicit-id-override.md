# Explicit-ID override

> Delivered by **S1.4** (#295). This is the elaboration of the one clause **GUIDE D6**
> spends on the exception to its own rule — *"connector mappings are **identity-agnostic**;
> one generic ID builder replaces the per-connector `generate_*_id` functions; a rare
> explicit-ID override exists for cross-source alignment"* — from half a sentence into a
> defined, tested path.
>
> The override is what makes centralization safe. Generated ids are dot-joined
> `_normalize`d segments, and some ids a graph needs are not that shape: a CSV that must
> land on the same `:BusinessTerm` node Dataplex already minted needs `projects/p/…/terms/x`,
> not `ecommerce_glossary.revenue_metrics.gmv`. Without an escape hatch, moving identity
> into the ID builder would delete that capability — `generate_business_term_id`'s own
> docstring currently advises using it.

## The contract

For any entity row in the normalized schema:

1. **Precedence** — an explicit id **wins**; when absent, the KeySpec-driven ID builder
   generates one from the row's natural key (#305).
2. **Opt-in** — the field defaults to `None`, so identity-agnostic remains the *default*
   and every row every connector emits today is unaffected.
3. **Verbatim** — an explicit id is never normalized, stripped or case-folded. That is the
   point: it reaches ids the generated shape cannot express.
4. **Blank means absent** — `""`, whitespace and NaN fold to `None`, so a partially-filled
   override column falls back to generation row by row.
5. **Entities only** — an edge carries no override; its endpoints resolve through the
   entity rows.

## Where it is declared (the S1.4 latitude call)

**A reserved optional field on the entity records, declared once, never aliased.**

`explicit_id: str | None = None` on the ten entity records — `DatabaseRecord`,
`SchemaRecord`, `TableRecord`, `ColumnRecord`, `ValueRecord`, `GlossaryRecord`,
`CategoryRecord`, `BusinessTermRecord`, `GovernanceTagKeyRecord`,
`GovernanceTagValueRecord` — declared through the field/validator factories in
[`normalized_schema/_identity.py`](../../neocarta/etl/metadata_normalizer/normalized_schema/_identity.py),
the single owner of the field (GUIDE §4), exactly as `_vocabulary.py` owns the field
vocabulary.

**Why a field and not a per-entity flag.** A flag cannot carry the id, so it needs a
companion column — two columns for one fact, which can contradict (`flag=True, value=None`).
Presence *is* the flag, so the contradiction is unrepresentable, the same structural move
`BusinessTermAssignmentRecord` makes for grain. A flag would also be a Graph Spec `source`
column meaning "read another column", which is not tabular (D14).

**Why entity records only.** A relationship is `MERGE`d on its endpoint pair and has no id
of its own; no loader accepts one. The field would be permanently unconsumed on
`ForeignKeyRecord`, `BusinessTermAssignmentRecord` and `LineageRecord` — the class of field
the [normalized-schema README](../../neocarta/etl/metadata_normalizer/normalized_schema/README.md)'s
*Not modelled* section already rejects (`References.constraint_name`). `NormalizedStructuralSchema`
is a container, not an entity, so it has none either. Entity / edge / bundle is asserted as
an exhaustive, disjoint partition, so a future record must be classified before it can exist.

**Why the two governance records get one even though no producer supplies an id.**
"Every entity record, no exceptions" is a rule a reviewer can check; "every entity record
except these two" is a table someone has to maintain.

**Why a factory, not a mixin.** Pydantic orders `model_fields` base-first, so a mixin would
put the deliberate D6 breach *ahead of every natural key* on all ten records — and would
make the carve-out silently inheritable, so a future record could acquire the one field the
guards are allowed to accept just by subclassing. A per-record
`explicit_id: str | None = explicit_id_field()` line is a visible, greppable opt-in at each
site.

**Why it is never aliased.** `AliasChoices` resolves to the first alias *present*, and a
source `*_id` column is not reliably a graph id. `_vocabulary.py` already spends three of
them on **name** concepts (`table_id` → `table_name`, `dataset_id` → `schema_name`,
`project_id` → `database_name`), and Dataplex's `glossary_id` / `category_id` / `term_id`
are **slugs**, and a Dataplex `term_id` is a whole resource path. Absorbing any of them is
strictly worse than the label-binding hazard S1.2 already documents, and the difference is
the verbatim rule: S1.2's trap only bites when a label differs from its slug by more than
case or separator (`_normalize` folds `-` and ` ` alike, so they often coincide), whereas an
aliased override diverges on **every** row because nothing normalizes it. Deterministically
broken beats intermittently broken for a guard's purposes — REVIEW.md 🔴 either way. So
`explicit_id` is the one field with `validation_alias=None`, and connectors project onto it
deliberately.

**Why blank folds to `None`.** An empty string is falsy but is not `None`. Left intact it
would reach `resolve_id`, be returned as the id, and collapse every row of that type onto a
single empty-id node — the same "never fabricate a key segment" failure `ValueRecord.value`
avoids with `coerce_str_required`. The fold reuses `coerce_key_segment_or_none`, the
validator S1.2 added for exactly this truthiness-vs-identity disagreement.

## Where it is applied

**The ID builder applies the precedence; the normalized model only declares the supplied id.**

[`resolve_id`](../../neocarta/etl/transform/explicit_id.py) lives in `etl/transform`. This is
the same split S1.3 made for the merge policy, and all four of its stated reasons re-derive:

| S1.3's reason (merge-contract.md) | The S1.4 mapping |
|---|---|
| "Non-clobber is a property of a write against prior state, not of a row." | Precedence needs the supplied id *and* the generated one, and the contract deliberately does not replicate the `generate_id` logic — so a row structurally cannot resolve itself. |
| "The normalized contract is deliberately graph-agnostic … declaring it there re-couples the contract to the ontology." | The *field* is a single, guarded breach the escape hatch cannot avoid. Resolving it against a KeySpec's output would be a second, avoidable one. |
| "The model→writer channel already exists." | The field **is** the model→transform channel. Nothing else is needed. |
| "One owner, and it moves as a unit." | GUIDE §5 maps `connectors/utils/generate_id.py` onto `etl/transform`, where #305 lands — so the rule is born in its final home and never moves. |

`None`, not falsiness, is the absence signal: the model has already folded blanks by the
time a row reaches the builder, so re-folding here would put two owners on one rule, and a
falsy check would silently reinterpret an id a caller genuinely supplied.

## Edges and endpoints

An edge has no override field, so #305 resolves each endpoint through an index built from
the entity rows:

```
endpoint_id(kind, key) = resolve_id(index.get((kind, key)), build_id(kind, key))
```

- `index` maps `(record class, natural-key tuple) → explicit_id` for every entity row **in
  the bundle** that carries one.
- **Keyed by record class, never by graph label.** `DatabaseRecord("proj")` and
  `GlossaryRecord("proj")` are both 1-tuples of `str`, so a discriminator is unavoidable —
  but it must be a contract-side one. A `NodeLabel` here would re-couple the contract to the
  ontology, the same reason facet rows carry no `source_label`.
- **A miss is "no override", never an error.** Today an edge whose endpoint has no entity row
  still gets a *generated* endpoint id computed from the edge row's own key segments (e.g.
  `column_term_info.csv` computes `column_id` from its own `database`/`schema`/`table`/`column`
  columns); the writer `MATCH`es it, finds nothing, and drops the edge. The index-miss fallback
  computes the same id from the same segments, so the drop stays bit-identical. Raising would
  turn today's silent drop into a crash.
- **Grain selects the class.** `BusinessTermAssignmentRecord`'s asset endpoint is a
  `ColumnRecord` when `column_name` is set and a `TableRecord` when it is `None`, so the
  grain-by-depth rule also decides whose override applies.
- **Per-bundle, never a cross-run cache** — and that is sufficient, because alignment works by
  each source declaring the same `explicit_id` on its own entity rows, so every bundle resolves
  to the same value independently.

## Parity: what today's connectors actually do

### CSV — the real override case

`connectors/csv/extract.py` implements the escape hatch as **twenty guarded sites across ten
distinct `*_id` columns**, each `if "<x>_id" not in df.columns: df["<x>_id"] = <generate>`. A
supplied value is used **verbatim**; only a missing column is generated.

| CSV file | Override columns honored today | Generated from |
|---|---|---|
| `database_info.csv` | `database_id` | `generate_database_id` |
| `schema_info.csv` | `schema_id`, `database_id` (parent) | `generate_schema_id`, `generate_database_id` |
| `table_info.csv` | `table_id`, `schema_id` (parent) | `generate_table_id`, `generate_schema_id` |
| `column_info.csv` | `column_id`, `table_id` (parent) | `generate_column_id`, `generate_table_id` |
| `value_info.csv` | `value_id`, `column_id` (parent) | `generate_value_id`, `generate_column_id` |
| `column_references_info.csv` | `source_column_id`, `target_column_id` | `generate_column_id` ×2 |
| `glossary_info.csv` | `glossary_id` | `generate_glossary_id` |
| `category_info.csv` | `category_id`, `glossary_id` (parent) | `generate_category_id`, `generate_glossary_id` |
| `business_term_info.csv` | `business_term_id`, `category_id` (parent) | `generate_business_term_id`, `generate_category_id` |
| `column_term_info.csv` / `table_term_info.csv` | `column_id` / `table_id`, `business_term_id` | as above |

Under the contract a **parent** column disappears: the override belongs on the parent's own
record and the child resolves through the index, so the "must be consistent across files"
burden `CSVExtractor`'s docstring places on the user is discharged by construction.

The shipped `datasets/csv/*.csv` carry **no** `*_id` columns, so the shipped dataset only
exercises the generated path.

### query_log — not an override case

`query_log` computes its ids *inside its own parser* with the same `generate_table_id` /
`generate_schema_id` / `generate_column_id`, carries them on the extracted frame, and
`transform.py` reads them straight off it (`Table(id=row.table_id)`), with only `Database`
regenerated. It is generate-early-pass-later, so **every structural id it emits is
reproducible from the natural-key names on the same frame** and it needs no override.
Its `Query` / `CTE` / query-owned-column ids are rooted on a SHA-256 of the query text —
the query paradigm, a separate normalized surface (D11) this contract does not model.

Two projection traps the parity suite pins, both of which mean a raw query-log frame must be
**projected** rather than validated directly:

- `table_info.dataset_id` is the **generated schema id** (`my_proj.sales`), not a dataset
  name — and `SCHEMA_NAME_SYNONYMS` absorbs `dataset_id` because in BigQuery and Dataplex
  frames that column *is* the name. A raw row carries neither `schema_name` nor
  `table_schema`, so a direct validate binds the id as the name — on every row, not as a
  corner case.
- `column_info.table_name` is the SQL **alias** (`o`), and the frame carries no container
  path at all, so a column's key is recoverable only by joining back to `table_info` on
  `table_id`.

## Granularity: file-level → row-level

Today the choice is per column: if a `*_id` column exists, *every* row in that file uses it
verbatim. The contract makes it per row, because a blank cell folds to `None` and falls back
to generation.

This cannot change any input that works today, and that is measured rather than reasoned. A
blank cell in a supplied id column short-circuits the `if "<x>_id" not in df.columns` guard, so
nothing is regenerated; pandas reads the cell as `NaN`, and that `numpy.float64` reaches
`Column(id=...)` where `id: str` is required, raising `ValidationError` (`string_type` on
`id`). Under the contract the same cell folds to `None` and the row generates
`db.s.t.c`. The only input whose meaning changes is one that currently crashes.

## Documented limits

- **Two rows asserting different explicit ids for one natural key** → out of scope, for the
  reason [merge-contract.md](merge-contract.md) already gives: "D10 is about *loss*, not
  *disagreement*; arbitrating conflicting authorities is a provenance question with no source
  of truth at this layer."
- **Uniqueness is the supplier's to own.** Two rows of the *same* kind sharing an explicit id
  is the alignment feature working — that is the whole point. Across *different* kinds it is
  neither checked nor rejected: the writer's `MERGE` is label-scoped, so one id supplied for
  both a column and a table yields two nodes rather than a conflict. Nothing is corrupted, and
  this is today's connector behavior unchanged. The index makes the same distinction for the
  same reason — keyed by *record class*, so a `DatabaseRecord` and a `GlossaryRecord` sharing a
  key never collide.
- **A bundle-level "explicit ids on/off" switch** is deliberately *not* offered. That is the
  file-level all-or-nothing model this ticket widens away from, and it would be a second
  owner of a fact the field already carries.
- **An override costs convergence with OSI, and that is the real price of using it.** OSI is
  the graph/semantic paradigm (D11): it never passes through this contract, and
  `OsiTransformer._make_column_id` derives every `:Column` id by *generating* — re-splitting
  the dotted table id and calling `generate_column_id` — so it has no override to consult. A
  physical column that a tabular connector overrides and an OSI model also describes therefore
  lands as **two** `:Column` nodes, where without the override the two converge on one. The
  escape hatch buys alignment with whichever source minted the id and spends alignment with
  OSI. Today's behavior unchanged — but it is why the override is *rare* rather than a
  general-purpose knob, and it is the same shape of OSI/tabular divergence
  [merge-contract.md](merge-contract.md) records for the key flags. Closing it means giving the
  graph/semantic transform its own override seam: S5's to decide, not this contract's.
- **`LineageRecord` has no producer** and its graph target is declared but not implemented,
  so its endpoint resolution is specified here and exercised by nothing.
- **The index is specified, not implemented.** Building it needs a per-type natural key —
  which *is* the KeySpec, and D6 says the ontology owns that. Implementing it here would
  create the second owner GUIDE §4 forbids, so it lands with #305.

## S4 reconciliation

- Connectors project their `*_id` columns onto `explicit_id` explicitly; nothing is absorbed
  by alias, and Dataplex's slug columns must **not** be projected.
- `column_references_info.csv` may today carry `source_column_id` / `target_column_id`
  independently of `column_info.csv`. Under the contract the override moves to the
  `ColumnRecord`. Every input conformant with `CSVExtractor`'s own documented rule
  ("Mixing … is not supported") stays byte-identical; the non-conformant one goes from a
  silently broken graph (explicit endpoint ids `MATCH`ing generated node ids, so the edge is
  dropped) to a consistent one.
- No golden covers the explicit-ID path, because the shipped datasets do not use it. **S4
  must capture an explicit-ID CSV golden before flipping** — the same handoff the README
  already makes for the Dataplex glossary pre-fold.

## Tests

| What | Where |
|---|---|
| Placement (entity vs edge vs bundle, as an exhaustive disjoint partition), optional-by-default, never aliased, source `*_id` columns do not populate it, verbatim, blank/NaN folds — plus the narrowed D6 guard that still rejects a *second* `*_id` field | `tests/unit/etl/metadata_normalizer/normalized_schema/test_models.py` |
| Precedence, idempotence, absence-is-`None`-not-falsiness, verbatim with a `_normalize` sensitivity control, and the model↔resolver composition | `tests/unit/etl/transform/test_explicit_id.py` |
| CSV parity against the **real `CSVExtractor`** for all eight entity id columns in both directions, HAS_SCHEMA and REFERENCES endpoint resolution, plus a negative control that degenerates the resolver | `tests/unit/etl/transform/test_csv_passthrough_parity.py` |
| query_log's negative proof (every structural id reproduces; no row needs an override), the two projection traps, and the query-paradigm boundary | `tests/unit/etl/transform/test_query_log_passthrough_parity.py` |

No integration test and no new golden: the mechanism is pure string precedence, so there is
nothing a live Neo4j can show that `resolve_id` cannot, and the endpoint-`MATCH` behavior an
IT would exercise is unchanged and already covered by
`tests/integration/connectors/csv/test_graph_golden_IT.py`. GUIDE §4's characterization-first
rule does not bite either: S1.4 refactors no code that any golden guards.
