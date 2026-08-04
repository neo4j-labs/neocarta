"""The standardized field vocabulary shared by every normalized-schema record.

Canonical token (the public field name) ⟵ the known source-column synonyms every
connector emits for that concept. Ratified by S1.5 (#296); this module is the single
owner of the **shared** mapping (GUIDE §4, "one owner per piece of state") so the
structural core (``models.py``) and the optional facets (``facets.py``) cannot drift
apart.

It is deliberately **not** the owner of every alias set: a set is shared only when
*every* record that has the field accepts the same names, so role-scoped
(``ForeignKeyRecord``'s ``source_*`` / ``target_*``) and record-scoped
(``description``, ``TableRecord.display_name``, ``GlossaryRecord.resource_path``) sets
stay inline at their declaration site. ``docs/refactor/field-vocabulary.md`` has the
full vocabulary and the reason that boundary is where it is.

Three rules every set keeps:

- **Canonical token first**, so it wins when both it and a synonym are present and
  a spin-out connector can always emit canonical names (GUIDE D17).
- **Collision-free across source columns**, and arbitrated by the rule above where
  an extractor frame adds its own: no connector's *source* columns spell one concept
  two ways, but ``CSVExtractor`` generates ``*_id`` columns, so a real CSV frame
  carries both ``table_name`` and a precomputed ``table_id``. Canonical-first is what
  makes that safe, because ``AliasChoices`` picks the first alias *present*, not the
  first non-null one — which is also why a concept whose canonical token means
  something else in another source must **not** absorb that source's column (see the
  glossary note in ``facets.py``).
- **Every synonym has a real producer** — each is a name some connector or shipped
  dataset actually emits, never one invented from plausibility. Enforced by
  ``test_no_invented_aliases``.
"""

# --- Structural core (S1.1) ---------------------------------------------------

DATABASE_NAME_SYNONYMS = (
    "database_name",  # jdbc, csv
    "project_id",  # bigquery, dataplex
    "table_catalog",  # bigquery / rdbms base (table + column frames)
    "catalog_name",  # unity catalog, rdbms base (schema frame)
    "database",  # snowflake (database frame)
    "catalog",  # databricks (database frame)
)
SCHEMA_NAME_SYNONYMS = (
    "schema_name",  # rdbms base, jdbc, unity catalog, csv
    "table_schema",  # bigquery / rdbms base (table + column frames)
    "dataset_id",  # bigquery, dataplex
)
TABLE_NAME_SYNONYMS = (
    "table_name",  # bigquery, rdbms base, jdbc, unity catalog, csv
    "table_id",  # dataplex (identity segment; display label is display_name)
)
DATA_TYPE_SYNONYMS = (
    "data_type",  # bigquery, rdbms base, csv
    "column_data_type",  # dataplex
    "type",  # jdbc
    "column_type",  # unity catalog
)
NULLABLE_SYNONYMS = (
    "nullable",  # jdbc, unity catalog
    "is_nullable",  # bigquery, rdbms base, csv
    "column_mode",  # dataplex ("NULLABLE" / "REQUIRED")
)

# --- Optional facets (S1.2) ---------------------------------------------------

VALUE_SYNONYMS = (
    "value",  # csv (value_info.csv required column)
    "unique_value",  # bigquery / rdbms base sampled-values frame (_VALUE_COLUMNS)
)
GLOSSARY_DISPLAY_NAME_SYNONYMS = (
    "display_name",  # canonical (matches TableRecord.display_name)
    "name",  # csv glossary_info / category_info / business_term_info label override
    # Deliberately absent: dataplex's ``glossary_name`` / ``term_name``. Those
    # columns are *labels* while identity lives in ``glossary_id`` / ``term_id``
    # — the inverse of CSV — so absorbing them here would let a raw Dataplex row
    # bind its label as the identity segment. The connector pre-folds instead.
)
TAG_NAMESPACE_SYNONYMS = (
    "tag_namespace",  # canonical
    "source",  # databricks/tags (_KEY_COLS / _VALUE_COLS): metastore id → host fallback
)
TAG_VALUE_SYNONYMS = (
    "tag_value",  # canonical
    "value_name",  # databricks/tags (_VALUE_COLS)
)
