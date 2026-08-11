# The connector mapping mechanism

> Ratified by **S1.6 (#297)**, the decision gate for how a connector's rows become normalized
> records and then canonical graph objects. Its verdict gates **#298**, **#306** and **all of
> S4**. Siblings: [`merge-contract.md`](merge-contract.md),
> [`explicit-id-override.md`](explicit-id-override.md),
> [`field-vocabulary.md`](field-vocabulary.md).

S1.1–S1.5 shipped the normalized schema as a **contract** — 13 record models, a ratified field
vocabulary, coercions, a merge policy, an explicit-ID override — and deliberately no way in:
there is no `normalize()` or `from_frame()` anywhere under `neocarta/`, and every connector
still hand-writes a `transform.py` (11 files, 2 590 lines). This ticket decides what fills that
gap, and whether the Neo4j **Graph Spec** should be it.

---

## 1. The decision

**The mechanism is the normalized schema's own vocabulary, plus two small pieces it was
missing:** a **record binder** (source rows → normalized records) and a per-connector **mapping
declaration**. The record→graph half is source-agnostic and lives once. Four escape hatches,
each named so its use is countable, cover what a declaration genuinely cannot express.

**Graph Spec is not the mapping mechanism and not the normalization standard.** It is retained
as a possible **emit-only** expression of the ontology half, with no runtime dependency — see
§3, which narrows **D14** and does so through **D13**.

Proven, not asserted: byte-identical output for **three divergent connectors** at **three
seams**, against goldens committed before this ticket. §5 has the numbers.

---

## 2. Why not Graph Spec

Assessed against the vendored, tag-pinned schema in
[`tests/support/graph_spec/`](../../tests/support/graph_spec/README.md)
(`org.neo4j.importer:import-spec`, **`v1.0.0-rc21`**). Every claim below is asserted in
`tests/unit/etl/test_graph_spec_ceiling.py`, so it re-checks itself as upstream moves.

### 2.1 A static property list conflicts with D10 — the primary reason

This is a collision with ratified design, not a missing feature. An entity target offers
exactly two knobs: `write_mode: create|merge` and a **static** `properties` array. Under
`merge`, every declared property is written on every row — and in Cypher
`SET n.description = null` **removes** the property. So a target declaring `description`
**erases a description another connector wrote**, on every row where this source has none.

That is precisely the non-clobber violation [`merge-contract.md`](merge-contract.md) was
ratified (S1.3, #294) to prevent and `MergePolicy.COALESCE` exists to stop. It cannot be
patched spec-side: the format has no `default`, no `expression`, no `filter`, and no per-batch
property scoping.

The corollary is the first hatch in §4.4. Property scope is not an incidental feature of our
connectors — it is a **D10 obligation** `merge-contract.md` assigns to "the connector /
normalizer", and today it is answered three different ways across four owners.

### 2.2 Adopting the `SourceProvider` SPI displaces the writer and the connector contract

Not "Java is awkward". Four concrete consequences:

- **Blast radius.** [`jdbc/schema/extract.py`](../../neocarta/connectors/jdbc/schema/extract.py)
  (440 lines) does shell out to `java` — via `_assert_java_available` and `build_command` — but
  it is *one optional* connector whose README already declares Java a host prerequisite. A
  mapping mechanism sits on the ingest path of **all 13** connectors, turning an optional
  prerequisite into a hard requirement across a 3.10–3.13 matrix.
- **The bridge direction is inverted.** SchemaCrawler is Java-**in**: JSON out, Python owns
  everything after. A Graph Spec runner is Java-**out** — it owns the Neo4j write, displacing
  `MergePolicy`, `_validate_properties_list`, the constraint/index modules and the
  `__neocarta_graph__` singleton. That collides with **D10**, **D12** and the S5 writer ticket.
- **CI-untestable by our own precedent.** JVM tests skip in CI (no `setup-java` in any of the
  five workflows), so the one component on every ingest path would have no CI coverage.
- **D17 is a Python contract.**
  [`connector-contract.md`](../../.claude/skills/neocarta-add-source-connector/connector-contract.md)
  is eighteen sections of Python API and `_base.py`'s Protocols are Python. A Java SPI means
  rewriting both, plus two skills.

### 2.3 The declarative surface is capped at rename plus cast

`$defs["target.entity.propertyMapping"]` is exactly
`{source_field, target_property, target_property_type}` with **`additionalProperties: false`** —
so the ceiling is enforced by the schema, not merely conventional. A full-text search of the
document finds **no** `transformation`, `aggregat`, `order_by`, `where`, `limit`, `default`,
`expression`, `literal`, `constant`, `unwind`, `explode`, `dedup` or `distinct`, and v1 has no
`source_transformations` block. Of the operation kinds our connectors actually perform, Graph
Spec expresses two.

One case is inexpressible outright. `BusinessTermAssignmentRecord`'s grain is its key-path
depth, with no `source_label` discriminator by design
([`facets.py`](../../neocarta/etl/metadata_normalizer/normalized_schema/facets.py)). A
`start_node_reference` names exactly **one** declared node target and there is no `where`
clause to split a mixed-grain source, so the polymorphic `TaggedWith`
(`Literal["Column", "Table", "Schema", "Metric"]`) needs **N** relationship targets, one per
grain.

### 2.4 "Push it into the source query" does not rescue it

The strongest counter-argument, and it fails on *runtime-shaped* sources rather than on
expressiveness. [`bigquery/schema/extract.py`](../../neocarta/connectors/bigquery/schema/extract.py)
builds its value-sampling SQL **per table from discovered column names**, with a Python-side
type filter skipping `ARRAY`/`STRUCT`/`GEOGRAPHY`/`JSON`/`BIGNUMERIC`, then `melt` → `explode`
→ `dropna` → `astype(str)` → per-row md5. A Graph Spec `source` is a static string in a JSON
document, so expressing this means generating the spec at runtime from extracted metadata —
all the same Python, **plus** an emitter, a JVM invocation and an IPC contract. Strictly more
parts for identical output.

And the `target.query` escape hatch replaces typed Python with untyped Cypher strings, losing
`_validate_properties_list`, which today rejects a property absent from the graph model — a
`REVIEW.md` 🔴 class of defect.

### 2.5 Not the normalization standard either

A `source` is `{type, name, …additionalProperties: true}` — a connection/query descriptor whose
real shape lives behind the Java `SourceProvider`. It carries no field vocabulary, so it cannot
express the ×6 container / ×4 data-type / ×3 nullability resolution `_vocabulary.py` owns.
S1.5's *structural* claim survives (our tables are flat, so each *can* be described as a
`source`), but "describable as a source" is not "is the standard".

**One boundary declared open.** `neo4j-pe-refs/README.md` — the external field-naming reference
the ticket cites — is not vendored and not in the tree, exactly as
[`field-vocabulary.md`](field-vocabulary.md) already recorded. This verdict rests on the
upstream **`spec.v1.json` at a pinned tag** instead, which is stronger evidence: the schema is
the normative artifact, and it is now in the repo where the earlier reference never was.

### 2.6 Churn risk (D13)

`maven-metadata.xml` lists **rc01 … rc21, no GA**.

| Release | Date |
|---|---|
| rc17 (the version the ticket cites) | 2026-07-01 |
| rc18 | 2026-07-16 |
| rc19 | 2026-07-17 |
| rc20 | 2026-07-17 |
| rc21 | 2026-07-29 |

Four releases in four weeks, and the cited version was already four behind before this ticket
started. rc20 was a dependency *downgrade*; rc16 bumped a JSON-schema-validator major. GUIDE §6
applies: adapt behind our boundary, don't block on it. An emit-only adapter is the cheapest
possible exposure — if the format moves, one serializer and one vendored file change and no
ingest path breaks. The ceiling tests are written to **fail** on a widening format, which is
the signal that this verdict deserves a fresh look.

---

## 3. What survives: Graph Spec as an emit-only ontology expression (narrowing D14)

**Raised per GUIDE §9, not deviated from.** D14's first clause is stated flatly — *"the
normalized-schema mapping and the ontology converge on **one** Neo4j-native Graph Spec
(import-spec) JSON lineage"* — so it must be reconciled rather than quietly reinterpreted.

**D13** is the reconciliation: the Neo4j-native ontology format is an evolving external
dependency kept *"behind an adapter"*, with our internal LPG model as source of truth. Read
together, "one lineage" means one **emitted** lineage, not one runtime substrate. Two merged
tickets already deferred the substrate to this spike, in the tree:
`normalized_schema/README.md` and `field-vocabulary.md` both say *"the final substrate is
decided by the S1 spike, not here."*

The narrowed form: **Graph Spec is an output format for the ontology/writer half, with zero
runtime dependency.** Its `targets` block does model what our writer does — `labels`,
`schema.key_constraints` / `unique` / `existence` / `type_constraints`, five index kinds,
`node_match_mode`, and `start/end_node_reference.key_mappings`. And because neocarta
pre-computes every node `id` in Python and every constraint is `REQUIRE x.id IS UNIQUE`, the
rename-only cap does not bite downstream: each key mapping is the trivial `<x>_id` → `id`.

So the honest shape of the finding: **Graph Spec is expressive enough exactly where we have
already done the hard work in Python, and D10-violating exactly where the ticket hoped it would
help.**

**Deferred, deliberately.** The emitter is specified here but **not built**. GUIDE §5 puts
ontology state in `etl/ontology/`, which is still an empty stub; an emitter today would have to
encode label, key and constraint knowledge that package is scheduled to own, making it a second
owner (GUIDE §4). It belongs with the ontology ticket. What lands now is the evidence — the
vendored schema and the ceiling tests — because that is what makes the verdict re-checkable.

---

## 4. The chosen mechanism

### 4.1 What was already there

The declarative layer is **the field vocabulary S1.1–S1.5 shipped**. Raw rows from three
different clusters validate into `ColumnRecord` with **zero** renames, coercions firing:

| Raw row, in the source's own vocabulary | → `ColumnRecord` |
|---|---|
| `{table_catalog, table_schema, table_name, column_name, data_type, is_nullable: "YES"}` (BigQuery) | `nullable=True` |
| `{catalog_name, schema_name, table_name, column_name, column_type, nullable: True, comment}` (Unity Catalog `ColumnInfo` TypedDict) | `data_type`, `description` |
| `{project_id, dataset_id, table_id, column_name, column_data_type, column_mode: "REQUIRED"}` (Dataplex) | `nullable=False` |
| `{database_name, schema_name, table_name, column_name, type, nullable: False}` (JDBC) | `data_type="int4"` |

Pinned in `tests/unit/etl/metadata_normalizer/test_binder.py`.

### 4.2 The two missing pieces

**A record binder** — `bind(rows: Iterable[Mapping[str, Any]], RecordType) -> list[Record]`.

Note the signature: **not** "frame → records". `UnityCatalogSchemaTransformer` consumes
`list[TypedDict]`, not frames, so a frame-first binder would exclude that cluster by
construction. The pandas adapter is a separate thin helper kept **outside**
`normalized_schema/`, because that package has no pandas import today and must keep none
(GUIDE §4 Model-Placement). Raw values — `NaN`, `numpy.bool_` — pass straight into
`model_validate`, because the contract's coercions are written to receive exactly those;
cleaning them in the binder would put a second owner on value handling.

**A per-connector mapping declaration** — which cached collection feeds which normalized
table, the source constants, the property scope, and the declared hatches. A table left out is
simply not emitted, which is how the sparse contract (**D10**) is expressed.

### 4.3 The record→graph half is source-agnostic

One implementation replaces the same ten-method shape hand-written eleven times. It derives the
containment edges (`HAS_SCHEMA` / `HAS_TABLE` / `HAS_COLUMN` / `HAS_VALUE` are not normalized
tables — they are *"fully derivable from the natural-key hierarchy each row carries"*), resolves
identity through `resolve_id(record.explicit_id, generate_*_id(...))`, and emits one edge per
child row in child-row order.

A parent endpoint prefers the parent's **resolved** id and falls back to generating one, so a
**D6** override on a parent propagates into its children's edges instead of being silently
dropped. The two are identical whenever no override is present, which is why today's output is
reproduced exactly.

### 4.4 The four escape hatches

Four fields on the declaration, named so their use is **countable** — the gate metric depends
on it, and `hatch_usage()` counts exactly these.

| Hatch | What it covers | Why a declaration cannot |
|---|---|---|
| `property_scope` | Which properties reach Neo4j per family | A ratified **D10** obligation, and the least declarative thing a connector does. Two live implementations need *different* inputs: JDBC reduces over the built **nodes** (`any(node.description is not None …)`), CSV filters the source **column names**. Hence a `ScopeContext` carrying both |
| `row_filter` | Drop a row on a source-field predicate | BigQuery's `constraint_type == "FOREIGN KEY"` pre-filter |
| `drop_self_references` | Drop a foreign key whose endpoints resolve to the same column id | Declarative flag, but **per-connector**: BigQuery and JDBC both drop this `INFORMATION_SCHEMA` join artefact while the shared RDBMS base and CSV do not. Making it universal would silently change connectors outside this proof set |
| `pre_fold` | A source-specific value transform that may raise | Dataplex's slug parsing; BigQuery's value-frame container-path recovery |

Two things are deliberately **not** hatches, though an earlier draft of this document counted
them as such:

- **`explicit_id`** is a field on the *records*, ratified by S1.4 and specified in
  [`explicit-id-override.md`](explicit-id-override.md). The mechanism consumes it through
  `resolve_id` and adds nothing; a connector opts in by projecting onto it, not by declaring
  anything here.
- **Staying hand-written** is a scope boundary, not an escape hatch. OSI keeps its transforms
  (`osi/ingest` 684 lines, `osi/export` 266 — two-pass fixpoint ordering, content-addressed
  cross-entity node collapsing, four-level nested descent, custom YAML representers) because it
  is the graph/semantic paradigm (**D11**) and was never in this mechanism's scope. Calling that
  a hatch would imply the tabular mechanism *could* have covered it.

### 4.5 Candidates benched

| Candidate | Verdict |
|---|---|
| Graph Spec SPIs | Rejected — §2 |
| pandera | Rejected. A frame *validation* library: it checks schemas, it does not map source vocabularies onto a target model. It would duplicate the `AliasChoices` layer that already exists (GUIDE §4, one owner) and add a runtime dependency for a job pydantic already does |
| pydantic `AliasChoices` + validators | **Chosen.** Already shipped, already test-pinned, zero new dependencies |
| Thin adapter code (a shared transform base) | **Chosen, as the complement.** Carries the reshaping that is genuinely code |
| Authoring-time agentic assistant | **Deferred, not rejected.** A future aid that emits a *static, reviewed, deterministic* declaration. **Never a runtime LLM in ingest.** Nothing precludes it: a declaration is plain reviewable Python |

### 4.6 Prior art, stated accurately

[`connectors/utils/rdbms_schema_transform.py`](../../neocarta/connectors/utils/rdbms_schema_transform.py)
reduces the Databricks and Snowflake schema transforms to **16 lines each**. It is worth citing
carefully, because it is easy to over-claim: it is **451 hand-written lines of
`for _, row in df.iterrows()` plus ten property blocks — not a declarative mapping** — and the
collapse works because Snowflake and Databricks are structurally *identical*. Two of its three
ClassVars are literals, and the third, `_DATABASE_COLUMN`, is exactly what `AliasChoices` now
subsumes. So it shows *a shared transform collapses identical shapes*; it is **not** evidence
for declarative mapping over divergent ones. That is what §5 measures.

---

## 5. The gate metric

The ticket arms a **⚠ negative-outcome trigger**: *if the chosen mapping is as complex as or
more complex than today's per-connector shape, principle 2 has failed → escalate, don't silently
proceed.* GUIDE §9 wants that objectively checkable, so it is measured and asserted in
`tests/unit/etl/metadata_normalizer/test_gate_metric.py`.

| Connector | Declaration | Replaces | Ratio | Hatches used |
|---|---|---|---|---|
| `bigquery/schema` | **23 lines** | 466 | 20× | `pre_fold`, `row_filter`, `drop_self_references` |
| `jdbc/schema` | **11 lines** | 427 | 38× | `drop_self_references`, `property_scope` |
| `csv` | **18 lines** | 574 | 31× | `property_scope` |
| **Total** | **52 lines** | **1 467** | **28×** | four distinct hatches, no unnamed ones |

The shared mechanism is 1 121 lines, of which **575 are code** — the rest is docstrings — and it
amortizes across every connector that flips: it already replaces 1 467 lines for three, out of
2 590 across eleven.

**What the tests assert, and what they deliberately do not.** The measurement above was taken at
spike time and lives here; `test_gate_metric.py` asserts the two things that remain *ongoing*
invariants — a declaration stays under 40 lines, and no fifth unnamed hatch appears. It does
**not** re-assert the ratios, because pinning three production files' line counts would fail the
etl suite on any unrelated edit to them: a tax on other people's changes for a one-time finding.
Escalate rather than proceed if a declaration approaches its `transform.py` size, if a fifth
hatch appears, or if `property_scope` cannot be given one owner per connector.

**⚠ Trigger evaluated.** Two readings exist and both are defensible, so the decision is on the
record. *Reading A:* the pre-registered hypothesis for both Graph-Spec roles failed, which is
what a gate exists to surface. *Reading B, taken:* the trigger names **the chosen** mapping, and
AC-1 offers *"a chosen mechanism demonstrated … **or** a documented negative outcome"*, while the
ticket's own *"If viable, green-lights …"* already contemplates non-viability without
escalation. A rejected candidate plus a demonstrated simpler mechanism is the first branch. That
reading holds only because both of its conditions are met: "simpler" is measured above, and the
hatch list is closed-ended and asserted.

### 5.1 The real prize is not line count

Five decisions currently answered *differently* per connector get **one** answer:

| Decision | Today |
|---|---|
| FK target catalog | BigQuery derives **both** endpoints from `constraint_catalog`/`constraint_schema`, so cross-dataset FKs are wrong; the shared RDBMS base correctly uses `referenced_*` |
| `nullable` coercion | Three places: pydantic lax mode (BigQuery), explicit `.ne("NO")` in extract (Databricks/Snowflake), `coerce_nullable` (the contract) |
| PK/FK unknown-vs-false | Unity Catalog → `None`; Dataplex → `False`; CSV → `False`; OSI → `None` |
| Skip-null properties | Two incompatible mechanisms: a node reduction (JDBC) and a column-name predicate (CSV) |
| ID-generation location | Extract (CSV, query-log) vs transform (everything else) |

The BigQuery FK defect is **inside the committed golden**, so parity means reproducing it. It is
now also visible in a Layer R golden, where both endpoints show the same `database_name` —
which is the sort of localization that layer exists for. Fixing it is its own ticket, with the
golden diff as the record.

---

## 6. The proof (AC-1)

Three connectors, three seams. Every oracle was committed **before** this ticket.

| Seam | What is compared | Where |
|---|---|---|
| **Layer R** (new) | The normalized records each connector emits | `tests/unit/etl/metadata_normalizer/test_normalized_records.py` + `golden/` |
| **Layer A** | The graph models, against the **existing** committed goldens, unchanged | `tests/unit/etl/mapping_spike/test_parity.py` |
| **Layer B** | Post-ingest Neo4j graph state, against the **existing** graph goldens | `tests/integration/etl/test_mapping_spike_graph_IT.py` |

Results: BigQuery **10/10** families byte-identical (including equality with
`bigquery_schema_transform.json` as a file); JDBC **8/8**; CSV **17/17** of the families the
tabular contract covers. Both property-scope allowlists match the production reductions exactly.
Layer B reproduces both committed graph goldens.

**Why this needed neither #298 nor a KeySpec builder.** `serialize_transform` is duck-typed — it
reflects over whatever `*_nodes` / `*_relationships` properties an object exposes. A prototype
emitting **today's legacy `data_model` classes** through **identically-named** accessors, using
the existing `generate_*_id` functions, is comparable against today's goldens directly. The repo
already split this obligation: `test-quality-inventory.md` row 1 assigns byte-for-byte
*central-transform* reproduction to **S3**, and row 5 assigns *normalized-record* golden-mastering
to **this band**.

**Documented exclusion.** CSV also emits `query_nodes`, `cte_nodes`, `uses_table_relationships`,
`uses_column_relationships` and `defines_relationships` — families with **no normalized table
at all**, because the query surface is a separate ingestion paradigm (**D11**), listed under
*"Not modelled (and why)"* in `normalized_schema/README.md`. The CSV comparison covers the
tabular families and a test asserts the uncovered set is exactly this list, so the subset is
reported rather than glossed.

**Where the prototype lives, and why.** `tests/support/mapping_spike/` — uncollected and outside
`coverage source`. #298/S3 owns `metadata_normalizer` and `etl/transform`, so a second
implementation under `neocarta/` would be a second owner (GUIDE §4). The **goldens** are the
permanent half and do live in the production test tree: when S4 rewrites a connector to emit
records directly, those files are what prove it emits the same ones.

> **Superseded in part by S1.7 (#298).** That ticket promoted the prototype's *record* half —
> the binder, the declaration types, the hatches and the per-connector declarations — into
> `neocarta/etl/metadata_normalizer/` and `neocarta/connectors/<source>/mapping.py`, and this
> package now re-exports them so there is still exactly one implementation. What remains a
> prototype here is `transform.py`, the record→graph half, which is **S3**'s. The three Layer R
> goldens moved with their suite to `tests/unit/etl/metadata_normalizer/golden/` and are
> reproduced by the production component byte for byte.

### 6.1 Connectors deliberately not in the proof set

The ticket recommended `unity_catalog/schema` and `dataplex/glossary`. Both were measured and
set aside for reasons worth recording:

- **`dataplex/glossary`** is the most expensive connector in the repo to characterize.
  `tests/unit/connectors/dataplex/glossary/` contains **only** `test_conformance.py` — no
  conftest, no fixtures, no extract/transform tests — and there is no
  `tests/integration/connectors/dataplex/` at all. Worse, its `TaggedWith` endpoints are
  `entity_id` / `business_term_id`: **graph ids minted inside the extractor**, which **D5** makes
  private and `test_entry_link_ids_are_not_accepted` pins as non-aliasable. Proving it requires
  changing `extract.py` — **S4 scope**. The repo's own characterization list omits Dataplex too.
- **`unity_catalog/schema`** is 100 % declarable, which is the case nobody doubted; as evidence
  of declarability it is padding. Its real contribution is being the one `list[TypedDict]` cache,
  and that question is settled by the binder's `Iterable[Mapping]` signature and its tests.

`jdbc/schema` replaced them because it carries the capability Layer A is **blind** to, and has a
committed offline fixture. `osi/*` is out of scope by **D11**.

---

## 7. Two defects this spike surfaced

Both are fixed here, and both mattered beyond it.

**The #291 harness could not see four of nine tabular transformers.**
`serialize_transform` discovered families only through `@property` accessors, but Unity Catalog,
both Dataplex connectors and Databricks tags assign theirs as plain instance attributes in
`__init__`. For those it returned `{}` — and an empty dict compares equal to an empty golden, so
anyone capturing one would have committed a characterization test that passed while guarding
nothing. Since every S4 cutover is meant to be guarded by a Layer A golden captured first
(GUIDE §4), four connectors could not have had one. Fixed, with all ten counts pinned in
`tests/unit/etl/test_characterization_discovery.py`.

**The shared BigQuery value seed carried three columns the real extractor never emits.**
`project_id` / `dataset_id` / `table_name` were added speculatively under a comment claiming the
fixture "mirrors the real extractor"; the extractor declares its value frame as exactly
`["column_name", "unique_value", "column_id", "value_id"]` and writes nothing else. Nothing read
them, so no golden was wrong — but the trap was live: a normalizer built against the fixture
would have passed in tests and failed on real data, surfacing during the S4 cutover instead of
here. Removed, and the fixture's shape is now asserted against the extractor's own declaration
in `tests/unit/etl/test_characterization_fixtures.py`.

---

## 8. Output for the next tickets

**#315 — the connector-authoring contract.** §18 of
[`connector-contract.md`](../../.claude/skills/neocarta-add-source-connector/connector-contract.md):
what an author declares, what they no longer write, and the hatches as the reviewable
exceptions.

**#298 — the `metadata_normalizer` design.** Build in `neocarta/etl/metadata_normalizer/`:

1. **The binder**, promoted from the prototype. Signature `Iterable[Mapping[str, Any]]`, with
   the pandas adapter as a sibling module so `normalized_schema/` stays pandas-free.
2. **The declaration types** — `SourceTable` / `ConnectorMapping` / `ScopeContext` — and the four
   hatches as named fields. Keep `hatch_usage`: the gate metric needs it to stay measurable.
3. **The central transform** goes to `etl/transform/` (**S3**, GUIDE §5), not here, and should
   take the generic KeySpec builder (**#305**) in place of the `generate_*_id` calls the
   prototype makes. Its containment-edge derivation and child-row ordering transfer as-is.
4. **Property scope needs one owner.** It is currently four; the declaration is where it lands.
   Note the loader still exposes only `overwrite_existing: bool`, so surfacing `MergePolicy` on
   `load_*` is a prerequisite for the layer-2 half.
5. **Keep Layer R.** It is the seam that localizes an S4 regression to a connector rather than a
   pipeline.
6. **`transform()` must assign, not accumulate.** Today's transformers overwrite their caches, so
   re-running one is a no-op; the prototype originally appended and silently doubled every family.
   A connector's `transform()` is re-callable after a failed `load()`, so this is reachable in
   normal use. Found by hostile testing, pinned by `TestTransformIsRepeatable`.

7. **The governance facet is the one real coverage gap.** The prototype consumes 10 of the
   contract's 13 tables; `governance_tag_keys` / `governance_tag_values` are unconsumed and
   `databricks/tags` therefore has **0 of its 3 families** covered. (`lineage` is the third
   unconsumed table and has no producer at all, per S1.2.) Measured, not estimated:
   `query_log` by contrast is already at **8 of 13** families, the other five being the D11
   query surface.

**Not in scope for either:** the Graph Spec emitter (§3), the generic writer (S5), and OSI
(**D11**).

### 8.1 Coverage measured across all nine tabular connectors

The proof set is three, but the mechanism was cold-tested against the rest — a declaration
written from the extractor's frames with no prior work on that connector:

| Connector | Result |
|---|---|
| `bigquery/schema` | byte-identical, **live-verified** (684 objects from real BigQuery) |
| `jdbc/schema` | byte-identical, **live-verified** (real Java + SchemaCrawler + Postgres) |
| `csv` | byte-identical on 17 of 20 families (3 are D11) |
| `unity_catalog/schema` | byte-identical, cold |
| `databricks/schema` | byte-identical, cold |
| `snowflake/schema` | byte-identical, cold |
| `dataplex/schema` | identical **except** `is_primary_key`/`is_foreign_key`: it fabricates `False`, the contract correctly yields `None`. That is the ratified D10 tri-state divergence, so the mechanism is *more* correct — and it is the S4 reconciliation `field-vocabulary.md` already lists |
| `query_log` | 8 of 13 families; the rest are the D11 query surface |
| `databricks/tags` | **0 of 3** — needs the governance facet (see point 7) |

So seven of nine reproduce today's output exactly, one diverges in the direction the contract
mandates, and one is a real gap with a named owner.

---

## 9. Documented limits

Two that are not simply restatements of a section above:

- **The verdict is only as current as the pin.** It is asserted against `v1.0.0-rc21`, and the
  ceiling tests are written to fail if a later RC widens the format. That failure is the **D13**
  signal to revisit §2, not a flake to silence; re-pinning steps are in
  `tests/support/graph_spec/README.md`.
- **The gate metric counts declaration lines, not cognitive load.** 52 lines replacing 1 467 is
  simpler on any reading, but the metric would not catch a mechanism that stayed small by
  becoming inscrutable. That is what review is for.

Also, and stated where they arise rather than repeated here: `neo4j-pe-refs` remains unvendored
(§2.5), the proof set is three connectors of eleven (§6.1), CSV's query families are excluded by
**D11** (§6), and the prototype is throwaway with #298 owning the real component (§6).

## 10. Tests

| What | Where |
|---|---|
| The Graph-Spec expressiveness ceiling, incl. the D10 conflict and the pinned version | `tests/unit/etl/test_graph_spec_ceiling.py` |
| Layer A parity for all three connectors, plus file equality with the BigQuery golden | `tests/unit/etl/mapping_spike/test_parity.py` |
| Per-connector sensitivity controls (a collapsed id helper must break parity) | same file, `TestSensitivity` |
| Property-scope equality against JDBC's and CSV's production reductions | same file, `TestPropertyScopeParity` |
| Layer R goldens + dropped-field and reordering negative controls | `tests/unit/etl/metadata_normalizer/test_normalized_records.py` |
| Layer B post-ingest graph parity (Docker) | `tests/integration/etl/test_mapping_spike_graph_IT.py` |
| The binder: no-rename binding per cluster, raw pandas values, non-pandas caches, hatch order | `tests/unit/etl/metadata_normalizer/test_binder.py` |
| The gate metric and its trigger conditions | `tests/unit/etl/metadata_normalizer/test_gate_metric.py` |
| Harness discovery for all ten tabular transformers | `tests/unit/etl/test_characterization_discovery.py` |
| The BigQuery value seed matches the extractor's declared columns | `tests/unit/etl/test_characterization_fixtures.py` |
