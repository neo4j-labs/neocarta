# The metadata normalizer

The runtime realization of the mapping mechanism **S1.6 (#297)** ratified: a connector's private
extractor cache in, the [normalized schema](normalized_schema/README.md) out. Built by **S1.7
(#298)**.

S1.1–S1.5 shipped the normalized schema as a *contract* — 13 record models, a ratified field
vocabulary, coercions, a merge policy, an explicit-ID override — and deliberately no way in. This
package is the way in.

```python
from neocarta.connectors.bigquery.schema.mapping import BIGQUERY_SCHEMA
from neocarta.etl.metadata_normalizer import normalize

output = normalize(extractor, BIGQUERY_SCHEMA)
output.records["columns"]   # sparse: only the tables this connector declares
output.as_schema()          # the ratified NormalizedStructuralSchema bundle
```

## The parts

| Module | What it owns |
|---|---|
| [`declaration.py`](declaration.py) | `SourceTable` / `ConnectorMapping` / `ScopeContext`, the four named hatches, `hatch_usage` |
| [`hatches.py`](hatches.py) | Shared implementations of the two hatches most connectors use identically |
| [`binder.py`](binder.py) | Source rows → normalized records. Thin, because the records already own renaming and coercion |
| [`_frames.py`](_frames.py) | The pandas adapter — the only module here that knows what a frame is |
| [`normalizer.py`](normalizer.py) | `normalize`, composing the above into the one call S3/S5 consume |
| [`normalized_schema/`](normalized_schema/) | The shared, source-agnostic tabular contract (S1.1–S1.5) |

A **per-connector declaration** lives with its connector, at
`neocarta/connectors/<source>/mapping.py`. That placement is a GUIDE §4 call: a declaration names
the extractor's *private cache* keys (**D5**), so it is connector-internal knowledge, and **D17**
makes it the connector author's artifact. It is added **alongside** the hand-written
`transform.py`, which still runs — the cutover is S4 (GUIDE §2, additive dual-path).

## What it deliberately does not do

- **No record→graph mapping.** That half is source-agnostic and belongs to `etl/transform`
  (**S3**), with the KeySpec-driven ID builder (#305).
- **No identity.** `explicit_id` is carried on the record and resolved downstream by
  `etl/transform.resolve_id` (**D6**). This package never mints, reads or resolves an id.
- **No value cleaning.** Raw `NaN` and `numpy.bool_` reach `model_validate` untouched, because the
  contract's coercions are written to receive exactly those. Folding a blank to `None` belongs to
  `normalized_schema/_identity.py`, not here (GUIDE §4, one owner).

## Two shapes of output, and why

`NormalizedRecords.records` is **sparse** — only declared tables appear — so **D10**'s *"this
connector does not produce that"* stays distinguishable from *"it produced nothing this run"*.
`as_schema()` projects onto `NormalizedStructuralSchema`, whose 13 tables all default to `[]` and
therefore **cannot** express that difference.

So the sparse mapping is the state and the bundle is a view of it, not the other way round.
Holding the bundle as the state would silently widen every connector to the full contract.

## The four hatches

Named so their use is **countable** — the S1.6 gate metric is "declaration LOC plus how many
hatches", and a fifth appearing is a documented trigger to escalate rather than a feature.

| Hatch | Uses | What it covers | Shared implementation |
|---|---|---|---|
| `pre_fold` | 5 | A source-specific row transform that may raise | `container_path_from` — split a precomputed id back into the natural key |
| `property_scope` | 4 | Which properties reach Neo4j per family (a **D10** obligation) | `static_scope` — a constant list per family |
| `drop_self_references` | 2 | Drop a foreign key whose endpoints resolve to the same column | — |
| `row_filter` | 1 | Drop a row on a source-field predicate | — |

12 uses across the five connectors, and still only four named hatches.

Sharing two of the four implementations is the point of the gate metric rather than a violation of
it: `hatch_usage` still counts one use per declaration site. The forms that are genuinely bespoke —
JDBC's whole-collection reduction and CSV's column-presence filter — stay hand-written next to the
connector that needs them, because they are not the same operation with different arguments.

`explicit_id` is **not** a hatch (it is a field on the records, S1.4), and neither is *staying
hand-written* (that is a scope boundary — OSI is the graph/semantic paradigm, **D11**).

## Coverage

Five connectors are declared, each with a Layer R golden captured from its **real** extractor
driven offline. Four run against an oracle already committed to the repo; `databricks/tags` runs
against a dozen lines of SDK-shaped stand-ins, because SDK objects cannot be committed as data. The
first three reproduce goldens committed by S1.6 **byte for byte**, from a different implementation
than the one that captured them.

| Connector | Tables | Hatches | Why this one |
|---|---|---|---|
| `bigquery/schema` | 6 | `pre_fold`, `row_filter`, `drop_self_references` | AC-1, and the widest hatch use |
| `jdbc/schema` | 5 | `drop_self_references`, `property_scope` | AC-1; the whole-collection scope form |
| `csv` | 10 | `property_scope` | AC-1; 10 tables, the widest surface |
| `databricks/tags` | 2 | `property_scope` | the governance gap §8.7 names for this ticket |
| `query_log` | 5 | `pre_fold` ×4, `property_scope` | the only source that *fabricates* rows |

**Everything else flips in S4, not here.** The remaining tabular connectors each need their own
real fixtures at cutover, so declaring them now would mean inventing seed data and freezing a
golden captured by the very code it guards. `osi/*` is out by **D11**, and `dataplex/glossary`
mints its `TaggedWith` endpoints as graph ids inside its *extractor*, which **D5** makes private
and non-aliasable, so declaring it needs an `extract.py` change.

**Divergences left visible rather than hatched away.** These connectors are not being cut over
here, and a golden that hides a divergence guards nothing:

- **A container path recovered from a generated id carries the normalized spelling.**
  `container_path_from` splits an `*_id` whose segments `generate_id` has already `_normalize`d
  (lowercased, `-`/space → `_`), so a record whose path comes from an id can spell its container
  differently from a sibling record that read the source column — `example_project_id` beside
  `example-project-id`. It affects `query_log`'s columns and foreign keys, and every connector's
  `values` rows (visible in the S1.6 BigQuery golden, where `values` say `test_project_id` and
  `columns` say `test-project-id`). Identity is unaffected — the S3 builder normalizes both to one
  id, which is why the S1.6 goldens were ratified with it — but the records are then not joinable
  on the *raw* natural key. The real fix is for the extractor to keep the container path it
  already had, which is an `extract.py` change and therefore S4.
- `bigquery/schema` derives **both** foreign-key endpoints from `constraint_catalog` /
  `constraint_schema`, so a cross-dataset FK names the wrong target catalog. The defect is inside
  the committed golden, so parity means reproducing it; fixing it is its own ticket.

Two limits worth stating plainly, both from `container_path_from`:

- **It splits right to left**, because only the trailing segment count is known. A database name
  legitimately contains dots — a domain-scoped GCP project is `example.com:my-project`, and
  `generate_id`'s `_normalize` maps `-` and space to `_` but leaves `.` and `:` alone — so a
  left-to-right split would count those as separators and reject the row. What it cannot recover
  is a dot in a *trailing* segment (a column literally named `addr.city`); the guard refuses that
  loudly rather than mis-splitting.
- **Its guard fails the whole `normalize()` call, not the offending row.** That is the right
  default when the alternative is minting wrong ids silently, but it is a behaviour difference
  from the legacy transforms, which pass the precomputed id through opaquely and never parse it.

## Graph Spec

There is no Graph Spec adapter here because there is nothing to adapt. S1.6 rejected it as both
the mapping mechanism and the normalization standard — primarily on a **D10** collision, not a
capability gap: an entity target offers only `write_mode` and a *static* `properties` array, so
under `merge` a declared `description` erases another connector's on every row where this source
has none. It survives only as a possible **emit-only** ontology expression with zero runtime
dependency, and that emitter is deliberately not built (it belongs with `etl/ontology`).

The isolation is asserted, not just described:
`tests/unit/etl/metadata_normalizer/test_boundary.py` walks the AST of every module under
`neocarta/` and fails if any of them names an import-spec artifact — and, in the same pass, that
`normalized_schema/` names no frame library and pandas stays confined to `_frames.py`.
