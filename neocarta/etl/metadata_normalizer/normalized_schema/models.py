"""The normalized structural-core contract: flat, source-agnostic entity tables.

These models are the *only* public output a schema connector emits (GUIDE D5).
They are **natural-key-addressed** — every row carries its full source name path
(``database_name`` → … → ``column_name``) — and **identity-agnostic**: no graph
IDs and no embeddings (GUIDE D6). Graph IDs are assigned downstream by the
KeySpec-driven ID builder from these raw key segments; the ``generate_id`` logic
is deliberately not replicated here.

Each record standardises the divergent field vocabulary every connector's
``transform.py`` uses today: the x4 container name, x4 data type, and x3
nullability names all resolve onto one canonical token per concept. Connectors'
raw source rows validate directly because each divergent field accepts its known
source synonyms via :class:`pydantic.AliasChoices` (canonical token first, so it
stays the public field name and a spin-out connector can always emit canonical
names — GUIDE D17). Value coercions (GUIDE D7) — nullability token folding, NaN
scrubbing, platform/service casing — run as ``field_validator``s; source-specific
nullability fallbacks stay in the connector.

Containment edges (``HAS_SCHEMA`` / ``HAS_TABLE`` / ``HAS_COLUMN``) are *not*
modelled here: they are fully derivable from the natural-key hierarchy each row
carries. Only the non-derivable cross-hierarchy foreign-key reference is a table
(:class:`ForeignKeyRecord`). See ``README.md`` for the vocabulary rationale and
the Graph Spec ``sources`` mapping sketch.

Scope is the RDBMS *structural* core (schema connectors). The query and
graph/semantic (OSI) paradigms are separate normalized surfaces (GUIDE D11).
"""

from pydantic import AliasChoices, BaseModel, Field, field_validator

from ....data_model._validators import coerce_nullable, coerce_str_or_none, coerce_upper

# --- Standardized field vocabulary -------------------------------------------
# Canonical token (the field name) ⟵ the known source-column synonyms every
# schema connector emits for that concept. Documented here pending #296
# ratification. The synonym sets are collision-free within a single source row
# (no connector row carries two names for the same concept), and the canonical
# token is listed first so it wins when both it and a synonym are present.

_DATABASE_NAME_SYNONYMS = (
    "database_name",  # jdbc, csv
    "project_id",  # bigquery, dataplex
    "table_catalog",  # bigquery / rdbms base (table + column frames)
    "catalog_name",  # unity catalog, rdbms base (schema frame)
    "database",  # snowflake (database frame)
    "catalog",  # databricks (database frame)
)
_SCHEMA_NAME_SYNONYMS = (
    "schema_name",  # rdbms base, jdbc, unity catalog, csv
    "table_schema",  # bigquery / rdbms base (table + column frames)
    "dataset_id",  # bigquery, dataplex
)
_TABLE_NAME_SYNONYMS = (
    "table_name",  # bigquery, rdbms base, jdbc, unity catalog, csv
    "table_id",  # dataplex (identity segment; display label is display_name)
)
_DATA_TYPE_SYNONYMS = (
    "data_type",  # bigquery, rdbms base, csv
    "column_data_type",  # dataplex
    "type",  # jdbc
    "column_type",  # unity catalog
)
_NULLABLE_SYNONYMS = (
    "nullable",  # jdbc, unity catalog
    "is_nullable",  # bigquery, rdbms base, csv
    "column_mode",  # dataplex ("NULLABLE" / "REQUIRED")
)


class DatabaseRecord(BaseModel):
    """A row of the normalized Database table (a source database/project/catalog)."""

    database_name: str = Field(
        ...,
        validation_alias=AliasChoices(*_DATABASE_NAME_SYNONYMS),
        description="The natural-key name of the database.",
    )
    platform: str | None = Field(
        default=None, description="The platform hosting the database.", examples=["GCP"]
    )
    service: str | None = Field(
        default=None, description="The service running the database.", examples=["BIGQUERY"]
    )
    description: str | None = Field(
        default=None,
        validation_alias=AliasChoices("description", "comment"),
        description="The description of the database.",
    )

    _uppercase = field_validator("platform", "service", mode="after")(coerce_upper)
    _normalize = field_validator("description", "platform", "service", mode="before")(
        coerce_str_or_none
    )


class SchemaRecord(BaseModel):
    """A row of the normalized Schema table (a source schema/dataset)."""

    database_name: str = Field(
        ...,
        validation_alias=AliasChoices(*_DATABASE_NAME_SYNONYMS),
        description="The natural-key name of the parent database.",
    )
    schema_name: str = Field(
        ...,
        validation_alias=AliasChoices(*_SCHEMA_NAME_SYNONYMS),
        description="The natural-key name of the schema.",
    )
    description: str | None = Field(
        default=None,
        validation_alias=AliasChoices("description", "comment"),
        description="The description of the schema.",
    )

    _normalize = field_validator("description", mode="before")(coerce_str_or_none)


class TableRecord(BaseModel):
    """A row of the normalized Table table (a source table or view)."""

    database_name: str = Field(
        ...,
        validation_alias=AliasChoices(*_DATABASE_NAME_SYNONYMS),
        description="The natural-key name of the parent database.",
    )
    schema_name: str = Field(
        ...,
        validation_alias=AliasChoices(*_SCHEMA_NAME_SYNONYMS),
        description="The natural-key name of the parent schema.",
    )
    table_name: str = Field(
        ...,
        validation_alias=AliasChoices(*_TABLE_NAME_SYNONYMS),
        description="The natural-key name (identity segment) of the table.",
    )
    display_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("display_name", "table_display_name"),
        description=(
            "A human label distinct from the identity segment, when the source "
            "provides one (e.g. Dataplex). Downstream label = display_name or table_name."
        ),
    )
    description: str | None = Field(
        default=None,
        validation_alias=AliasChoices("description", "table_description", "comment"),
        description="The description of the table.",
    )

    _normalize = field_validator("display_name", "description", mode="before")(coerce_str_or_none)


class ColumnRecord(BaseModel):
    """A row of the normalized Column table.

    Resolves the x4 container / x4 data-type / x3 nullability source-name
    divergence onto canonical tokens, and coerces the nullability value (GUIDE
    D7). Key metadata defaults to ``None`` ("source said nothing") rather than
    ``False`` (GUIDE D10 sparse rows); ``nullable`` keeps the permissive ``True``
    default matching the graph model.
    """

    database_name: str = Field(
        ...,
        validation_alias=AliasChoices(*_DATABASE_NAME_SYNONYMS),
        description="The natural-key name of the parent database.",
    )
    schema_name: str = Field(
        ...,
        validation_alias=AliasChoices(*_SCHEMA_NAME_SYNONYMS),
        description="The natural-key name of the parent schema.",
    )
    table_name: str = Field(
        ...,
        validation_alias=AliasChoices(*_TABLE_NAME_SYNONYMS),
        description="The natural-key name of the parent table.",
    )
    column_name: str = Field(..., description="The natural-key name of the column.")
    data_type: str | None = Field(
        default=None,
        validation_alias=AliasChoices(*_DATA_TYPE_SYNONYMS),
        description="The data type of the column (may be absent in some sources).",
    )
    nullable: bool = Field(
        default=True,
        validation_alias=AliasChoices(*_NULLABLE_SYNONYMS),
        description="Whether the column can be null.",
    )
    is_primary_key: bool | None = Field(
        default=None,
        description="Whether the column is a primary key; None when the source exposes no key metadata.",
    )
    is_foreign_key: bool | None = Field(
        default=None,
        description="Whether the column is a foreign key; None when the source exposes no key metadata.",
    )
    description: str | None = Field(
        default=None,
        validation_alias=AliasChoices("description", "column_description", "comment"),
        description="The description of the column.",
    )

    _coerce_nullable = field_validator("nullable", mode="before")(coerce_nullable)
    _normalize = field_validator("data_type", "description", mode="before")(coerce_str_or_none)


class ForeignKeyRecord(BaseModel):
    """A row of the normalized foreign-key table (the cross-hierarchy REFERENCES edge).

    The only structural relationship that is not derivable from the natural-key
    hierarchy, so it is carried explicitly. Source and target columns are each
    addressed by their full natural key; role-scoped aliases keep the source and
    target sides distinct even when a connector's FK frame names them separately
    (``table_*`` vs ``referenced_*``) or shares one (``constraint_*`` /
    ``database_name``).
    """

    source_database_name: str = Field(
        ...,
        validation_alias=AliasChoices(
            "source_database_name", "table_catalog", "constraint_catalog", "database_name"
        ),
        description="Database of the referencing (source) column.",
    )
    source_schema_name: str = Field(
        ...,
        validation_alias=AliasChoices("source_schema_name", "table_schema", "constraint_schema"),
        description="Schema of the referencing (source) column.",
    )
    source_table_name: str = Field(
        ...,
        validation_alias=AliasChoices("source_table_name", "table_name"),
        description="Table of the referencing (source) column.",
    )
    source_column_name: str = Field(
        ...,
        validation_alias=AliasChoices("source_column_name", "column_name"),
        description="The referencing (source) column.",
    )
    target_database_name: str = Field(
        ...,
        validation_alias=AliasChoices(
            "target_database_name", "referenced_catalog", "constraint_catalog", "database_name"
        ),
        description="Database of the referenced (target) column.",
    )
    target_schema_name: str = Field(
        ...,
        validation_alias=AliasChoices(
            "target_schema_name", "referenced_schema", "constraint_schema"
        ),
        description="Schema of the referenced (target) column.",
    )
    target_table_name: str = Field(
        ...,
        validation_alias=AliasChoices("target_table_name", "referenced_table"),
        description="Table of the referenced (target) column.",
    )
    target_column_name: str = Field(
        ...,
        validation_alias=AliasChoices("target_column_name", "referenced_column"),
        description="The referenced (target) column.",
    )
    criteria: str | None = Field(
        default=None,
        description="The join condition for the reference, when the source provides one.",
    )

    _normalize = field_validator("criteria", mode="before")(coerce_str_or_none)


class NormalizedStructuralSchema(BaseModel):
    """The structural-core tabular contract a schema connector emits (GUIDE D5).

    A bundle of the entity tables plus the foreign-key table. Sparse by design:
    a connector populates only the tables it produces (GUIDE D10).
    """

    databases: list[DatabaseRecord] = Field(default_factory=list, description="The Database rows.")
    schemas: list[SchemaRecord] = Field(default_factory=list, description="The Schema rows.")
    tables: list[TableRecord] = Field(default_factory=list, description="The Table rows.")
    columns: list[ColumnRecord] = Field(default_factory=list, description="The Column rows.")
    foreign_keys: list[ForeignKeyRecord] = Field(
        default_factory=list, description="The foreign-key (REFERENCES) rows."
    )
