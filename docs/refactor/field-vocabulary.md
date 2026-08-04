# Canonical field vocabulary

> Delivered by **S1.5** (#296). This is the elaboration of **GUIDE D7** — *"normalization needs value
> coercions (not just field renames)"* — into the ratified vocabulary a connector author writes
> against, and the ratification
> [`_vocabulary.py`](../../neocarta/etl/metadata_normalizer/normalized_schema/_vocabulary.py) and the
> [`normalized_schema` README](../../neocarta/etl/metadata_normalizer/normalized_schema/README.md) have
> both been deferring to.
>
> The divergence is real and it is wide: seven schema connectors spell *the database a column lives in*
> six different ways (`database_name`, `project_id`, `table_catalog`, `catalog_name`, `database`,
> `catalog`), the *data type* four ways, and *nullability* three ways in three different value domains.
> Absorbing those spellings is what lets a connector's **raw** frame validate directly, while the
> canonical token stays the public field name so a spin-out connector can always emit canonical names
> without editing this contract (D17).

## The contract

Every field of every normalized record is named by a **canonical token** — the field name, and what
`model_dump()` emits. A field whose concept has divergent source spellings additionally accepts those
spellings as `validation_alias=AliasChoices(...)`. Three rules hold for every set:

1. **Canonical token first.** It wins when both it and a synonym are present, and it is what a
   spin-out connector can always emit (D17).
2. **Collision-free across *source* columns; arbitrated by rule 1 where a frame adds its own.** No
   connector's source columns spell one concept two ways. Extractor **frames** are a different matter:
   `CSVExtractor` generates `*_id` columns for the explicit-ID escape hatch, so a real CSV column frame
   carries both `table_name` (`orders`) and a precomputed `table_id`
   (`demo_e_commerce.demo_ecommerce.customers`) — two accepted names for one field in one row. Rule 1 is
   what makes that safe rather than corrupting: `AliasChoices` picks the first alias **present**, not the
   first non-`None` one, and the canonical token is first, so the name always beats the generated id
   (pinned by `test_table_name_wins_over_table_id_when_both_present`). The same mechanic is why a concept
   whose canonical token means something *else* in another source must not absorb that source's column —
   see the Dataplex omission under [Documented limits](#documented-limits).
3. **Every synonym has a real producer.** Each is a name some connector or shipped dataset actually
   emits, never one invented from plausibility. Enforced by `test_no_invented_aliases`.

Renaming is only half of it (D7). Where the *value domains* also diverge, a validator folds them —
`nullable` accepts `YES`/`NO`, `NULLABLE`/`REQUIRED` and native bools via `coerce_nullable`;
`description`/`data_type` scrub `NaN` → `None`; `platform`/`service` upper-case. Source-specific tokens
stay the connector's to pre-fold; see [S4 reconciliation](#s4-reconciliation).

## The vocabulary

Keyed the way the code is keyed: **`(record, field)`**. Most sets are shared by every record that has the
field, and those are in Table 1. Three concepts differ *per record*, and collapsing them into one
concept-keyed row is precisely how a reader ends up believing a glossary row's `comment` column is
absorbed when it is not — so they get their own table.

### Table 1 — Shared sets

Owned by [`_vocabulary.py`](../../neocarta/etl/metadata_normalizer/normalized_schema/_vocabulary.py)
(one owner, GUIDE §4). Record names below drop the `Record` suffix.

| Concept | Canonical token | Synonyms absorbed | Records |
|---|---|---|---|
| container: database / project / catalog (×6) | `database_name` | `project_id`, `table_catalog`, `catalog_name`, `database`, `catalog` | Database, Schema, Table, Column, Value, BusinessTermAssignment |
| container: schema / dataset (×3) | `schema_name` | `table_schema`, `dataset_id` | Schema, Table, Column, Value, BusinessTermAssignment |
| container: table (×2) | `table_name` | `table_id` | Table, Column, Value, BusinessTermAssignment |
| data type (×4) | `data_type` | `column_data_type`, `type`, `column_type` | Column |
| nullability (×3) | `nullable` | `is_nullable`, `column_mode` | Column |
| sampled value (×2) | `value` | `unique_value` | Value |
| glossary-side label (×2) | `display_name` | `name` | Glossary, Category, BusinessTerm |
| tag namespace (×2) | `tag_namespace` | `source` | GovernanceTagKey, GovernanceTagValue |
| tag value (×2) | `tag_value` | `value_name` | GovernanceTagValue |

`tag_namespace` is canonically named rather than borrowing Databricks' `source` column, because
`source_*` already means "the referencing side of an edge" on `ForeignKeyRecord` (Table 3). The raw
column still validates via the alias (D17).

### Table 2 — Record-scoped sets

Declared inline at each field, **not** in `_vocabulary.py`. An em dash means the field accepts its
canonical name only.

| Record | Field | Synonyms absorbed |
|---|---|---|
| `DatabaseRecord` | `description` | `comment` |
| `SchemaRecord` | `description` | `comment` |
| `TableRecord` | `description` | `table_description`, `comment` |
| `ColumnRecord` | `description` | `column_description`, `comment` |
| `BusinessTermRecord` | `description` | `term_description` |
| `GovernanceTagKeyRecord` | `description` | `tag_description` |
| `GlossaryRecord` | `description` | — |
| `CategoryRecord` | `description` | — |
| `TableRecord` | `display_name` | `table_display_name` |
| `GlossaryRecord` | `resource_path` | `glossary_resource_path` |
| `CategoryRecord` | `resource_path` | — |
| `BusinessTermRecord` | `resource_path` | — |

`display_name` is the one concept that appears in **both** tables, with different sets: the glossary-side
records absorb CSV's bare `name` label-override column, while `TableRecord` absorbs Dataplex's
`table_display_name`. Downstream label is `display_name or <identity segment>` in both cases.

### Table 3 — Role-scoped: `ForeignKeyRecord`

An FK row names two endpoints, so the two sides are scoped by role rather than sharing one set. Some
connectors name the sides separately (`table_*` vs `referenced_*`), and some share one prefix
(`constraint_*`), so several names appear on **both** sides — resolved by which field they are declared on.

| Field | Synonyms absorbed |
|---|---|
| `source_database_name` | `table_catalog`, `constraint_catalog`, `database_name` |
| `source_schema_name` | `table_schema`, `constraint_schema` |
| `source_table_name` | `table_name` |
| `source_column_name` | `column_name` |
| `target_database_name` | `referenced_catalog`, `constraint_catalog`, `database_name` |
| `target_schema_name` | `referenced_schema`, `constraint_schema` |
| `target_table_name` | `referenced_table` |
| `target_column_name` | `referenced_column` |

### Canonical-only fields

The remaining **41** scalar fields accept their canonical name and nothing else, which is what makes the
three tables above exhaustive: `column_name`, `glossary_name`, `category_name`, `term_name`, `tag_key`,
`platform`, `service`, `is_primary_key`, `is_foreign_key`, `criteria`, `explicit_id`, and **every field of
`LineageRecord`**. `LineageRecord` mirrors `ForeignKeyRecord`'s `source_*` / `target_*` *naming* but
declares no `validation_alias` at all — it has no producer yet (see *Not modelled* in the
[`normalized_schema` README](../../neocarta/etl/metadata_normalizer/normalized_schema/README.md)), so
absorbing a synonym would breach rule 3.

`explicit_id` is deliberately never aliased; the reasoning is in
[`explicit-id-override.md`](explicit-id-override.md).

## Where it is declared (the S1.5 latitude call)

**Shared sets live in `_vocabulary.py`; role-scoped and record-scoped sets stay inline at their
declaration site.** Of the 40 alias-bearing field declarations across the 14 exported models, 24 draw
their set from `_vocabulary.py` and 16 are inline (the 8 `ForeignKeyRecord` role-scoped fields, 6
`description` fields, `TableRecord.display_name`, `GlossaryRecord.resource_path`).

The rule that decides which is which: **share a set only when every record that has the field accepts the
same names.** Otherwise sharing *widens* a record's accepted inputs past what its own producers emit.

That is not a stylistic preference, and `description` is the worked example. A single
`DESCRIPTION_SYNONYMS = ("description", "comment", "table_description", "column_description",
"term_description", "tag_description")` would be tidier and would make `GlossaryRecord` accept
`column_description` — a name no glossary producer emits — and `CategoryRecord` accept `comment`, which
Unity Catalog emits for *columns*. Worse, it would pass the guard: `test_no_invented_aliases` proves a
synonym has a producer **somewhere** in `neocarta/connectors/` + `datasets/`, not that it has a producer
**for that record**. The narrow sets are the only thing enforcing per-record honesty, so they stay where
a reviewer reads them next to the field.

**Why this doc is prose and not generated from the models.** GUIDE §4 puts one owner on each piece of
state. Membership is owned by `model_fields` — `_vocabulary.py` for the shared sets, the declaration site
for the inline ones — so a generated or CI-diffed markdown table would make this file a second owner of
the same state and then need a reconciler to keep the two honest. What this doc owns instead is what the
code cannot state: the three rules, the shared-vs-inline decision procedure, the per-connector parity
projection, and the ratification itself. The counts it quotes *are* pinned, in the tests below, because a
count is the one claim here that a code change can silently falsify — as the pre-S1.5 "×4 container"
comment proved when `DATABASE_NAME_SYNONYMS` grew to six.

## Parity: what today's connectors emit

Column-grain frames, from the audited raw rows the contract tests validate (`RAW_COLUMN_ROWS`). "—" means
the connector does not produce the concept at all, which is distinct from producing it empty.

| Connector | database | schema | table | data type | nullability | description |
|---|---|---|---|---|---|---|
| `bigquery/schema` | `table_catalog` | `table_schema` | `table_name` | `data_type` | `is_nullable` — `"YES"`/`"NO"`, passed through raw | `description` |
| `dataplex/schema` | `project_id` | `dataset_id` | `table_id` | `column_data_type` | `column_mode` — `"NULLABLE"`/`"REQUIRED"`/`"REPEATED"` | `column_description` |
| `snowflake/schema`, `databricks/schema` | `table_catalog` | `table_schema` | `table_name` | `data_type` | `is_nullable` — pre-folded to `bool` by the extractor | `description` (SQL `AS`, from `comment`) |
| `jdbc/schema` | `database_name` | `schema_name` | `table_name` | `type` | `nullable` — native `bool` | `description` |
| `unity_catalog/schema` | `catalog_name` | `schema_name` | `table_name` | `column_type` | `nullable` — native `bool` | `comment` |
| `csv` | `database_name` | `schema_name` | `table_name` | `data_type` | `is_nullable` — `"true"`/`"false"` | `description` |
| `query_log`, `*/logs` | `project_id` | `dataset_id` ⚠ | `table_id` / `table_name` ⚠ | — | — | — |
| `osi/ingest` | parsed from the dataset `source` string | " | " | — | — | — |

`snowflake/schema` and `databricks/schema` share one frame (`RdbmsSchemaTransformer`) at table and column
grain, but diverge at **database** grain, where the name is the connector's own constructor argument:
Snowflake spells it `database`, Databricks `catalog`. Those are the two of the six container names that
appear in no column-grain frame.

Facet-side, the same shape holds: the sampled-values frames carry `unique_value` (bigquery, snowflake,
databricks) against CSV's `value`; `databricks/tags` carries `source` / `tag_key` / `tag_description` /
`value_name`; Dataplex's glossary frames carry `glossary_resource_path` and a `display_name` where CSV
carries a bare `name`.

⚠ **Deliberately not absorbed.** The query-log family's `left_*` / `right_*` join columns and its `*_id`
columns are excluded, and there the exclusion is load-bearing rather than tidy: its `dataset_id` holds a
**generated schema id** (`my_proj.sales`), not a dataset name, while `dataset_id` *is* an accepted
`schema_name` synonym because in BigQuery and Dataplex frames that column really is the name. A raw
query-log row carries neither `schema_name` nor `table_schema`, so validating one directly would bind the
id as the name — on every row. Its `column_info.table_name` is likewise the SQL *alias*. Both are pinned
by `test_query_log_passthrough_parity.py`. OSI is the graph/semantic paradigm (D11) and does not pass
through this contract at all.

## Graph Spec alignment (D14)

The canonical tokens are exactly the `columns` of a tabular Graph Spec (import-spec) `source`. Every
record is flat — each field is a scalar, asserted by `test_every_field_is_a_scalar` — so each table is one
`source` with no flattening step, and a facet table whose rows imply a relationship becomes a
relationship `target` keyed on the natural-key columns the row already carries. The worked sketch is in
the [`normalized_schema` README](../../neocarta/etl/metadata_normalizer/normalized_schema/README.md)
(*Not precluding a Graph Spec `sources` expression*) and is not duplicated here.

Two honest boundaries. First, `neo4j-pe-refs/README.md` — the external Graph Spec `sources` field-naming
reference this ticket cites — is **not vendored in this repo**, so the tokens here were not diffed
field-by-field against it; the alignment claim is structural (flat tables → `sources`), not name-level.
Second, per GUIDE §6 Graph Spec is an *"evolving external dependency (it is RC) — adapt behind our
boundary, don't block on it"*, so nothing above is pinned to a Graph Spec release. The substrate is
decided by the S1 spike, not here.

## Documented limits

- **`test_no_invented_aliases` is corpus-wide, not per record.** It greps
  `neocarta/connectors/**` + `datasets/**` for each synonym, so it catches an invented name but not a
  real name attached to the wrong record — the gap the narrow record-scoped sets exist to cover.
- **The counts are ×6 / ×4 / ×3** — container, data type, nullability. Pre-S1.5, `models.py` and the
  #292 CHANGELOG entry both said "×4 container", which was true when S1.1 landed and went stale when
  `database` and `catalog` were added for the Snowflake/Databricks database frame; both are corrected as
  part of this ticket. The ×4-vs-×6 distinction that *is* real is about frames, not the tuple: 4 of the
  6 names appear in a table/column-grain frame, 2 only at database grain.
- **The Dataplex `*_id` omission is what keeps rule 2 true.** Dataplex's glossary frames are the inverse
  of CSV's: identity lives in `glossary_id` / `category_id` / `term_id` while `glossary_name` /
  `term_name` hold the **display label**. Because `AliasChoices` resolves to the first alias *present*,
  absorbing those `*_id` columns onto the identity fields would silently bind the label as identity for
  any raw Dataplex row. They are not absorbed; the connector pre-folds the slug instead.
- **No field is an enum, and none will become one without a test failing.**
  `test_every_field_is_a_scalar` admits only `str` / `bool` / `int` / `float` and their `| None` forms, so
  `data_type` carries each source's raw spelling (`INT64`, `NUMBER`, `INTEGER`, `int`) with no
  canonicalization at this layer, and `platform` / `service` are upper-cased free text rather than a
  closed vocabulary.
- **No markdown drift guard, by decision.** The tables here are audited by hand against
  `model_fields` and the counts are pinned in the tests below. If S4 makes external or spin-out
  connectors contribute synonyms by PR, or if this doc ever grows an exhaustive per-`(record, field)`
  table of *every* alias, that trade flips — build the guard then, as a pytest walking `model_fields`
  across `normalized_schema.__all__` rather than parsing this file's prose.

## S4 reconciliation

The contract absorbs *names* and the standardized nullability vocabulary; anything source-specific stays
the connector's to project before it validates.

- **Dataplex** must pre-fold `column_mode` values beyond `NULLABLE`/`REQUIRED`. `coerce_nullable`
  deliberately rejects `REPEATED` rather than guessing, whereas the connector today evaluates
  `column_mode == "NULLABLE"`, which silently makes a `REPEATED` column *not nullable*. It must also
  keep pre-folding its glossary slugs, for the reason above.
- **query_log** must project `schema_name` / `table_name` from names rather than passing its `dataset_id`
  / `table_name` columns through, per the two pinned traps.

The value-coercion reconciliations that are not about naming — CSV's `NaN` reaching
`ValueRecord.value`, and Dataplex's fabricated key flags — stay with the records that own them in the
[`normalized_schema` README](../../neocarta/etl/metadata_normalizer/normalized_schema/README.md).

## Tests

| What | Where |
|---|---|
| The ×6 / ×4 / ×3 counts, pinned as full-tuple equality so a new synonym fails rather than staling this doc | `tests/unit/etl/metadata_normalizer/normalized_schema/test_models.py` — `TestContainerDivergence`, `TestDataTypeDivergence`, `TestNullabilityDivergenceAndCoercion` |
| Every synonym resolves onto its canonical token, per frame grain, and the nullability value-domain matrix (`YES`/`NO`, `NULLABLE`/`REQUIRED`, native bools) with `REPEATED` rejected | the same three classes, plus `TestCoerceNullableUnit` |
| Every synonym has a real producer somewhere in `neocarta/connectors/` + `datasets/` | `test_facets.py::TestEverySynonymHasARealProducer::test_no_invented_aliases` |
| Canonical-first arbitration where a frame carries both a name and a generated id (rule 2) | `test_models.py::test_table_name_wins_over_table_id_when_both_present` |
| The per-connector parity table: each connector's audited raw row validates onto the canonical record without loss | `test_models.py` `RAW_COLUMN_ROWS`; `test_facets.py` `RAW_VALUE_ROWS` / `RAW_GLOSSARY_ROWS` / `RAW_CATEGORY_ROWS` / `RAW_BUSINESS_TERM_ROWS` / `RAW_TERM_ASSIGNMENT_ROWS` / `RAW_GOVERNANCE_KEY_ROWS` |
| Every field is a scalar, so no field is an enum and every table is one Graph Spec `source` | `test_facets.py::TestEveryTableIsFlat::test_every_field_is_a_scalar` |
| The Dataplex identity columns are **not** aliased, and the private extractor-cache graph ids are not accepted (D5) | `test_facets.py::test_dataplex_identity_columns_are_not_aliased`, `::test_sampling_frame_ids_are_not_accepted`, `::test_entry_link_ids_are_not_accepted` |
| `explicit_id` is the one field with no alias | `test_models.py::test_override_is_never_aliased` |
| The query-log projection traps (`dataset_id` is a generated id; `column_info.table_name` is a SQL alias) | `tests/unit/etl/transform/test_query_log_passthrough_parity.py` |

No new test file and no integration test: the vocabulary is validation-time alias resolution, already
exercised by the two contract suites, and S1.5 refactors no code any golden guards.
