# Normalized schema: structural core + optional facets

The flat, standardized, **natural-key-addressed** tabular contract every schema
connector emits — the source-agnostic substrate that decouples connectors from
the ontology (GUIDE §6). This is the connector's **only** public output (D5);
the extractor cache stays private.

The structural core is defined in [`models.py`](models.py), the optional facets in
[`facets.py`](facets.py), and the shared field vocabulary in
[`_vocabulary.py`](_vocabulary.py) (one owner, GUIDE §4). Delivered by S1.1 (#292)
and S1.2 (#293) as a **contract**: no runtime path uses it yet — connectors flip
to it in S4, proven at parity against the #291 characterization harness.

## What it is

The structural core — five row models plus the bundle:

| Model | One row is | Natural key |
|---|---|---|
| `DatabaseRecord` | a database / project / catalog | `database_name` |
| `SchemaRecord` | a schema / dataset | `database_name`, `schema_name` |
| `TableRecord` | a table or view | `database_name`, `schema_name`, `table_name` |
| `ColumnRecord` | a column | `database_name`, `schema_name`, `table_name`, `column_name` |
| `ForeignKeyRecord` | a `REFERENCES` edge | source + target column keys |
| `NormalizedStructuralSchema` | the whole emitted contract | — |

…and the optional facets that hang off it:

| Model | One row is | Natural key |
|---|---|---|
| `ValueRecord` | one sampled distinct value of a column | column key + `value` |
| `GlossaryRecord` | a business glossary | `glossary_name` |
| `CategoryRecord` | a category of a glossary | `glossary_name`, `category_name` |
| `BusinessTermRecord` | a term in a category | `glossary_name`, `category_name`, `term_name` |
| `BusinessTermAssignmentRecord` | a term applied to a table or column (`TAGGED_WITH`) | asset key × term key |
| `GovernanceTagKeyRecord` | a governance tag key | `tag_namespace`, `tag_key` |
| `GovernanceTagValueRecord` | one allowed value of a key | `tag_namespace`, `tag_key`, `tag_value` |
| `LineageRecord` | one observed data-flow edge | source key × target key |

Each facet is omitted **independently** by leaving its table(s) empty:

| Facet | Table(s) on the bundle |
|---|---|
| values | `values` |
| references | `foreign_keys` (the structural core's own table) |
| lineage | `lineage` |
| glossary | `glossaries`, `categories`, `business_terms`, `business_term_assignments` |
| governance | `governance_tag_keys`, `governance_tag_values` |

### Facet coverage, enumerated per connector

What each connector actually produces today, and the record that expresses it.
Verified by driving each connector's real extractor/transformer and validating the
same frame through the contract.

| Connector | values | references | lineage | glossary | governance |
|---|---|---|---|---|---|
| `bigquery/schema` | ✅ | ✅ | — | — | — |
| `databricks/schema` | ✅ | ✅ | — | — | — |
| `snowflake/schema` | ✅ | ✅ | — | — | — |
| `csv` | ✅ | ✅ | — | ✅ all four tables | — |
| `jdbc` | — | ✅ | — | — | — |
| `dataplex/schema` | — | — | — | — | — |
| `dataplex/glossary` | — | — | — | ✅ (pre-folded) | — |
| `databricks/tags` | — | — | — | — | ✅ definition layer |
| `unity_catalog` | — | — | — | — | — |
| `query_log`, `*/logs` | — | ⚠️ see below | — | — | — |
| `osi/ingest` | — | ⚠️ | — | ⚠️ terms only | — |

Two ⚠️ qualifications, both deliberate:

- The **query-log family** derives references from parsed joins and names them
  `left_*` / `right_*`. The *facet* is expressible — the rows are ordinary
  `ForeignKeyRecord`s once the connector projects canonical names — but those raw
  column names are **not** absorbed as aliases, because the query paradigm is a
  separate normalized surface (D11) and S1.1 made the same call for the structural
  core this connector also fabricates.
- **OSI** is the graph/semantic paradigm (D11), not a tabular one. Its
  synonym-derived business terms are expressible as `BusinessTermRecord`s, but its
  positional references and its `Metric`-grain tagging are not — a `Metric` key is
  `(semantic_model, metric)`, a different hierarchy rather than a deeper segment of
  this one.

No connector produces **lineage** at all; see *Not modelled* below.

### Design rules (with the decision each honors)

- **Source-derived fields only — no graph IDs, no embeddings** (D6). Identity is
  assigned downstream by the KeySpec-driven ID builder from the raw key segments
  each row carries; the `generate_id` logic is not replicated here.
- **Natural-key-addressed, so containment is implicit.** A `ColumnRecord` already
  carries its full `database/schema/table` path, so `HAS_SCHEMA` / `HAS_TABLE` /
  `HAS_COLUMN` are derivable and are **not** modelled as tables. Only the
  cross-hierarchy foreign-key reference — which cannot be derived — is a table.
  The same rule removes five facet edges; see *Edges that vanish* below.
- **Facets are independently omittable** (D10). Every facet table is
  `default_factory=list`, so there is nothing to switch off: a connector that
  emits only the structural core validates unchanged.
- **No graph labels, so the attach grain is derived** (D6, GUIDE §6). The graph's
  polymorphic `TAGGED_WITH` carries `source_label` + `source_id`; a facet row
  instead addresses its asset by an unbroken **prefix** of the natural-key path,
  and the grain is the deepest populated segment. `column_name` is the only
  optional segment, so a column-grain row always carries its table path and a
  gapped path is *unrepresentable* rather than merely rejected. Table and column
  are the only grains a tabular producer emits today; the Schema and Metric grains
  the graph also allows come only from the OSI paradigm (D11), and widening the
  path later is additive. A **blank** optional segment folds to `None`
  (`coerce_key_segment_or_none`): an empty string is falsy but is not `None`, so
  leaving it intact would let one consumer read the row as table-grain and another
  as column-grain. Only blank folds — a real name is never stripped.
- **Sparse rows** (D10). Key metadata (`is_primary_key` / `is_foreign_key`)
  defaults to `None` = "the source said nothing", never a fabricated `False`, so
  the [non-clobber merge](../../../../docs/refactor/merge-contract.md) can't let a
  partial row erase a fuller one — a tri-state field is protected by value
  coalescing on its own. `nullable` keeps the permissive `True` default to match
  the current graph model, and is therefore the one field that is *not*: having no
  "unknown", its default is indistinguishable from an asserted `True`, so only the
  writer's property-scope layer (leaving it out of the write entirely, as
  `connectors/query_log` already does) keeps a sparse row honest about it. Note the
  one place `None` means something else: in a facet **key** segment it means "the
  path ends here" (the grain), which does not collide with the unknown-vs-false
  rule because the grain-bearing records carry no attribute columns at all.
- **Value coercions, not just renames** (D7). `nullable` folds the standardized
  token vocabulary (`YES`/`NO`, `NULLABLE`/`REQUIRED`, native bools) via
  `coerce_nullable`; `description`/`data_type` scrub NaN → None;
  `platform`/`service` upper-case. Source-specific fallbacks (e.g. Dataplex
  `REPEATED` → not nullable) stay in the connector.
- **A key segment is never fabricated** (D10). `ValueRecord.value` uses
  `coerce_str_required`: a numeric cell is cast (a dtype-inferred frame can hand
  it an `int`, and today's producers stringify upstream) but `None`/NaN are left
  for Pydantic to reject, because the value is a key segment whose id
  content-hashes it — coercing a missing cell to `""` would mint a real node for
  absent data. `GovernanceTagValueRecord.tag_value` goes further and is
  **uncoerced**, so `High Risk` / `high-risk` / `high_risk` stay distinct exactly
  as the content-hashed id requires.

### Edges that vanish, and edges that stay

An edge between a key path and one of its own prefixes needs no table:

| Graph edge | Derived from | Modelled? |
|---|---|---|
| `HAS_SCHEMA` / `HAS_TABLE` / `HAS_COLUMN` | the entity row's own key path | no |
| `HAS_VALUE` | a value row's column key path | no |
| `HAS_CATEGORY` | `(glossary_name, category_name)` | no |
| `HAS_BUSINESS_TERM` | `(glossary_name, category_name, term_name)` | no |
| `HAS_VALUE_OPTION` | `(tag_namespace, tag_key, tag_value)` | no |
| `HAS_DEFINITION` | **non-locally** — the natural-key join of an assignment against `governance_tag_values` on `(tag_namespace, tag_key, tag_value)` | no |
| `REFERENCES` | not derivable (cross-hierarchy) | **yes** — `ForeignKeyRecord` |
| `TAGGED_WITH` → `:BusinessTerm` | not derivable (cross-hierarchy) | **yes** — `BusinessTermAssignmentRecord` |
| `INPUT_TO` / `PRODUCES` (declared, **not implemented** graph-side) | not derivable | **yes** — `LineageRecord` |

`HAS_DEFINITION`'s set membership *is* the graph's semantics — an applied value
with no matching definition is a free-form value — so a fabricated `is_governed`
flag could only disagree with the authoritative join.

## Standardized vocabulary (proposed; #296 to ratify)

Each canonical token — the field name, and what `model_dump()` emits — accepts
the known source synonyms via `AliasChoices` (canonical listed first), so a
connector's **raw** source row validates directly and a spin-out connector can
always emit canonical names without editing this contract (D17).

| Concept | Canonical token | Source synonyms absorbed |
|---|---|---|
| container | `database_name` | `project_id`, `table_catalog`, `catalog_name`, `database`, `catalog` |
| schema | `schema_name` | `table_schema`, `dataset_id` |
| table | `table_name` | `table_id` (Dataplex identity segment) |
| data type (×4) | `data_type` | `column_data_type`, `type`, `column_type` |
| nullability (×3) | `nullable` | `is_nullable`, `column_mode` |
| description | `description` | `comment`, `table_description`, `column_description`, `term_description`, `tag_description` |
| table label | `display_name` | `table_display_name` |
| sampled value | `value` | `unique_value` |
| glossary label | `display_name` | `name` (the CSV label-override column) |
| source resource path | `resource_path` | `glossary_resource_path` |
| tag namespace | `tag_namespace` | `source` |
| tag value | `tag_value` | `value_name` |

`ForeignKeyRecord` uses **role-scoped** aliases so a connector's FK frame that
names the two sides separately (`table_*` vs `referenced_*`) or shares one
(`constraint_*` / `database_name`) still resolves source and target distinctly.
`LineageRecord` uses the same role scoping for its two sides.

`tag_namespace` is canonically named rather than borrowing Databricks' `source`
column because `source_*` already means "the referencing side of an edge" on
`ForeignKeyRecord`; the raw column still validates via the alias (D17).

The synonym sets are collision-free within a single source row (no connector
emits two names for the same concept in one row) — with one deliberate omission
that keeps it that way. `AliasChoices` resolves to the first alias **present** in
the input, not the first non-null one, and Dataplex's glossary frames are the
*inverse* of CSV's: identity lives in `glossary_id` / `category_id` / `term_id`
while `glossary_name` / `term_name` hold the **display label**. Aliasing those
`*_id` columns onto the identity fields would therefore silently bind the label as
identity for any raw Dataplex row, so they are **not** absorbed: the connector
pre-folds the slug instead, exactly as it must already pre-fold `column_mode`.

## Connector notes (verified against real connector data)

- **BigQuery** — the real extractor frames carry extra columns
  (`constraint_name`, `table_type`, `creation_time`, `ddl`); these are ignored.
  The graph node id is reproducible from a record's raw natural key via
  `generate_column_id(...)`, so the identity-agnostic contract loses nothing the
  downstream ID builder needs.
- **CSV / MusicBrainz** — the shipped datasets already carry the canonical
  vocabulary: `column_info.csv` has the full `database/schema/table/column` path
  and lowercase `"true"/"false"` flags, and `column_references_info.csv` uses
  `source_*` / `target_* ` / `criteria` verbatim (i.e. `ForeignKeyRecord`'s
  canonical names). The CSV *format* allows optional columns, so a CSV that omits
  the path columns cannot populate the required natural-key fields — that is a
  malformed input for this contract, not something it silently accepts.
- **Dataplex** — currently fabricates `is_primary_key=False` / `is_foreign_key=False`
  (it exposes no key metadata); under this contract those become `None` (honest
  "unknown"). That is a deliberate behavior change to reconcile at the S4 flip
  (with a captured golden first). Its source-specific `column_mode` values beyond
  `NULLABLE`/`REQUIRED` (e.g. `REPEATED`) must be pre-folded by the connector; the
  contract does not silently accept unknown nullability tokens.
- **Sampled values** — the sampling frames are per-table and carry only
  `column_name` / `unique_value` plus the pre-computed `column_id` / `value_id`.
  The container path is *not* in the frame: it lives on the extractor call, which
  already passes it to the id builder. So the connector projects the path, and
  dropping the two ids is correct rather than lossy (D5). The three sampling
  producers all `dropna()` and `.astype(str)` upstream, so they cannot hit the
  rejected-NaN path; CSV can, and that is a listed S4 reconciliation.
- **Dataplex glossary** — identity segments are **slugs**
  (`glossary.name.split("/")[-1]`, `parse_category_slug`, `parse_business_term_slug`),
  the same dotted shape CSV uses, while the full GCP resource name is carried
  separately on `resource_path` and the human label on `display_name`. **This
  pre-fold is load-bearing and its omission is silent**: a raw Dataplex row also has
  a `glossary_name`/`term_name` column, so passing it unprojected still validates —
  it just binds the *label* as identity and yields the wrong id
  (`e_commerce_business_glossary` rather than `ecommerce_glossary`). The contract
  cannot tell the two apart, which is precisely why those `*_id` columns are not
  aliased and why the S4 flip needs a captured Dataplex-glossary golden first. Its entry
  links carry a pre-resolved graph id (`entity_id`) rather than segments, but the
  extractor already parses `project / dataset / table / column` out of the resource
  path to build that id, so it can emit the segments instead; its `entity_type`
  (`COLUMN` / `TABLE`) is exactly what the key-path depth now encodes.
- **Databricks tags** — contributes the definition layer only, plus the
  `tag_namespace` segment no other facet has (the metastore id, falling back to
  the workspace host). A governed key with no allowed values yields a key row and
  no value row.
- **CSV facet files** — already canonical: `value_info.csv`, `glossary_info.csv`,
  `category_info.csv`, `business_term_info.csv`, `column_term_info.csv` and
  `table_term_info.csv` use the canonical tokens verbatim, and the bare `name`
  column is the label override that maps onto `display_name`.

## Not modelled (and why)

Everything below is a graph-side concept with **no source to normalize**. Each is
additive when its producer lands (GUIDE §4), which is why none is guessed at now.

- **Value sampling statistics** — no producer anywhere computes a count,
  frequency, distinct count, null rate, inferred type or sampling timestamp.
- **The governance instance / assignment layer** — `GovernanceTag`,
  `HAS_DEFINITION` and the governance `TAGGED_WITH` have a complete loader and
  Neo4j constraints, but **zero** producers: Databricks ships the definition layer
  only, and reading assignments needs a SQL warehouse. Modelling the tabular half
  of a layer nothing emits would be speculative, not source-derived.
- **`GovernanceTagValue.description`** — the graph model has one, but the only
  producer sets it to `None` unconditionally.
- **Nested glossary categories** — Dataplex can nest them, but its connector keeps
  only the innermost slug, so the parent link is lost upstream and `Category` stays
  exactly one level deep as the graph model already is. (Its glossary-parented
  *terms* are separately dropped by the `/categories/` filter.)
- **FK `constraint_name` / `ordinal_position`** — partly source-available and then
  discarded (BigQuery selects both; the Databricks FK query projects only
  `ordinal_position`; Snowflake's frame carries neither), but `References` has nowhere to
  put them and the loader rejects any property absent from the graph model, so
  they would be permanently unconsumed contract fields. Composite grouping is
  recoverable anyway: the FK table is one row per column pair and BigQuery already
  orders by `ordinal_position`. Adding `References.constraint_name` is its own
  additive ticket touching the whole chain.
- **Query usage** (`USES_TABLE` / `USES_COLUMN` / `DEFINES` / `CTE`) and
  **OSI-owned attach points** (a `Metric`, a query-owned column keyed on a query
  hash) — separate normalized surfaces (D11). A query-owned column cannot be
  expressed here at all, because `ColumnRecord` requires a database/schema/table
  path; that is the boundary, not an oversight.
- **`embedding`** — comes from enrichment, never from a connector (D6).
- **Filtering and skip rules** — BigQuery's `constraint_type == "FOREIGN KEY"`
  filter and its self-referencing-FK skip are transform behavior, not contract
  shape, so S3 must reproduce them. (Related: BigQuery builds the FK *target* from
  `constraint_catalog`/`constraint_schema` where the RDBMS base correctly uses
  `referenced_*` — wrong for a cross-schema FK, and a golden-guarded fix either
  way, since the target aliases reproduce whichever the frame supplies.)

## Not precluding a Graph Spec `sources` expression (D14)

Every table — core **and** facet — maps cleanly onto a Neo4j-native Graph Spec
(import-spec) `sources → targets → actions` lineage: the natural-key-addressed
tabular shape *is* a Graph Spec tabular `source`, and a facet table whose rows
imply a relationship becomes a relationship `target`.

```jsonc
// sketch — neutral-but-compatible, not a committed format (Graph Spec is RC; see S1-SPIKE-1)
{
  "sources": [
    { "name": "columns", "type": "table",
      "columns": ["database_name","schema_name","table_name","column_name","data_type","nullable"] },
    { "name": "business_term_assignments", "type": "table",
      "columns": ["database_name","schema_name","table_name","column_name",
                  "glossary_name","category_name","term_name"] }
  ],
  "targets": {
    "nodes": [
      { "source": "columns", "labels": ["Column"],
        "key_properties": ["database_name","schema_name","table_name","column_name"],
        "properties": ["data_type","nullable"] }
    ],
    "relationships": [
      // Both endpoints are keyed on natural-key columns the row already carries —
      // no graph ids, and no source_label: the start node's label follows from
      // which key segments are populated (the row's grain).
      { "source": "business_term_assignments", "type": "TAGGED_WITH",
        "start_node": { "labels": ["Column"],
                        "key_properties": ["database_name","schema_name","table_name","column_name"] },
        "end_node":   { "labels": ["BusinessTerm"],
                        "key_properties": ["glossary_name","category_name","term_name"] } }
    ]
    // ForeignKeyRecord and LineageRecord → the same shape, keyed on their source/target columns
  }
}
```

Every table stays flat — each record's fields are all scalars — so each is one
`source` with no flattening step. We stay behind our own boundary and adapt (D14:
"don't block on it"); the final substrate is decided by the S1 spike, not here.
