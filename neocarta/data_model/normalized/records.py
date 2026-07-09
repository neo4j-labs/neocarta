"""Flat, scalar record models for the normalized-metadata intermediate.

These records mirror a source catalog's structural metadata. They carry only
name-parts (no deterministic ids) and no embeddings; those are produced later in
the graph-transform step. Field names deliberately follow the source/catalog
convention (``data_type``, ``is_nullable``) rather than the graph model's
(``type``, ``nullable``), and primary/foreign-key flags default to ``None``
("unknown") rather than ``False``.
"""

from pydantic import BaseModel, Field, field_validator

from .._validators import (
    coerce_str,
    coerce_str_or_none,
    coerce_upper,
    coerce_yes_no_to_bool,
)


class DatabaseRecord(BaseModel):
    """A flat database (catalog) record identified by its name."""

    database_name: str = Field(..., description="The name of the database")
    platform: str | None = Field(default=None, description="The platform hosting the database")
    service: str | None = Field(default=None, description="The service running the database")
    description: str | None = Field(default=None, description="The description of the database")

    _uppercase = field_validator("platform", "service", mode="after")(coerce_upper)
    _normalize = field_validator("description", "platform", "service", mode="before")(
        coerce_str_or_none
    )


class SchemaRecord(BaseModel):
    """A flat schema (dataset) record identified by its database and schema names."""

    database_name: str = Field(..., description="The name of the parent database")
    schema_name: str = Field(..., description="The name of the schema")
    description: str | None = Field(default=None, description="The description of the schema")

    _normalize = field_validator("description", mode="before")(coerce_str_or_none)


class TableRecord(BaseModel):
    """A flat table record identified by its database, schema and table names."""

    database_name: str = Field(..., description="The name of the parent database")
    schema_name: str = Field(..., description="The name of the parent schema")
    table_name: str = Field(..., description="The name of the table")
    table_type: str | None = Field(
        default=None, description="The table type (e.g. BASE TABLE, VIEW)"
    )
    description: str | None = Field(default=None, description="The description of the table")

    _normalize = field_validator("table_type", "description", mode="before")(coerce_str_or_none)


class ColumnRecord(BaseModel):
    """A flat column record identified by its database, schema, table and column names."""

    database_name: str = Field(..., description="The name of the parent database")
    schema_name: str = Field(..., description="The name of the parent schema")
    table_name: str = Field(..., description="The name of the parent table")
    column_name: str = Field(..., description="The name of the column")
    ordinal_position: int | None = Field(
        default=None, description="The 1-based position of the column within its table"
    )
    data_type: str | None = Field(default=None, description="The data type of the column")
    is_nullable: bool = Field(default=True, description="Whether the column can be null")
    is_primary_key: bool | None = Field(
        default=None,
        description="Whether the column is a primary key; None when the source exposes no key metadata",
    )
    is_foreign_key: bool | None = Field(
        default=None,
        description="Whether the column is a foreign key; None when the source exposes no key metadata",
    )
    description: str | None = Field(default=None, description="The description of the column")

    _normalize = field_validator("data_type", "description", mode="before")(coerce_str_or_none)
    _coerce_nullable = field_validator("is_nullable", mode="before")(coerce_yes_no_to_bool)


class ReferenceRecord(BaseModel):
    """A flat foreign-key row linking a source column to a target column by name-parts."""

    source_database_name: str = Field(..., description="The name of the source database")
    source_schema_name: str = Field(..., description="The name of the source schema")
    source_table_name: str = Field(..., description="The name of the source table")
    source_column_name: str = Field(..., description="The name of the source column")
    target_database_name: str = Field(..., description="The name of the target database")
    target_schema_name: str = Field(..., description="The name of the target schema")
    target_table_name: str = Field(..., description="The name of the target table")
    target_column_name: str = Field(..., description="The name of the target column")
    criteria: str | None = Field(
        default=None, description="The join condition between the two columns"
    )

    _normalize = field_validator("criteria", mode="before")(coerce_str_or_none)


class ValueRecord(BaseModel):
    """A flat sampled-value record for a column, identified by its name-parts."""

    database_name: str = Field(..., description="The name of the parent database")
    schema_name: str = Field(..., description="The name of the parent schema")
    table_name: str = Field(..., description="The name of the parent table")
    column_name: str = Field(..., description="The name of the parent column")
    value: str = Field(..., description="The sampled value cast to a string")

    _cast = field_validator("value", mode="before")(coerce_str)
