"""The core components of the RDBMS metadata graph data model."""

from pandas import isna
from pydantic import BaseModel, Field, field_validator


class Database(BaseModel):
    """A Database node."""

    id: str = Field(..., description="The unique identifier for the database")
    name: str = Field(..., description="The name of the database")
    platform: str | None = Field(
        default=None, description="The platform of the database", examples=["GCP"]
    )
    service: str | None = Field(
        default=None, description="The service running the database", examples=["BIGQUERY"]
    )
    description: str | None = Field(default=None, description="The description of the database")
    embedding: list[float] | None = Field(
        default=None, description="The embedding of the database description"
    )

    @field_validator("platform", "service", mode="after")
    def validate_string_uppercase(cls, v: str | None) -> str | None:
        """Validate that the string is in uppercase."""
        return v.upper() if v is not None else None

    @field_validator("description", "platform", "service", mode="before")
    def validate_string_or_none(cls, v: str | None) -> str | None:
        """
        Validate that the string is string type or None.
        This will cast NaN values to None.
        """
        if isinstance(v, str):
            return v
        if v is None or isna(v):
            return None

        return v


class Schema(BaseModel):
    """A Schema node (represents a BigQuery dataset)."""

    id: str = Field(..., description="The unique identifier for the schema")
    name: str = Field(..., description="The name of the schema")
    description: str | None = Field(default=None, description="The description of the schema")
    embedding: list[float] | None = Field(
        default=None, description="The embedding of the schema description"
    )

    @field_validator("description", mode="before")
    def validate_string_or_none(cls, v: str | None) -> str | None:
        """
        Validate that the string is string type or None.
        This will cast NaN values to None.
        """
        if isinstance(v, str):
            return v
        if v is None or isna(v):
            return None

        return v


class Table(BaseModel):
    """A Table node."""

    id: str = Field(..., description="The unique identifier for the table")
    name: str = Field(..., description="The name of the table")
    description: str | None = Field(default=None, description="The description of the table")
    embedding: list[float] | None = Field(
        default=None, description="The embedding of the table description"
    )

    @field_validator("description", mode="before")
    def validate_string_or_none(cls, v: str | None) -> str | None:
        """
        Validate that the string is string type or None.
        This will cast NaN values to None.
        """
        if isinstance(v, str):
            return v
        if v is None or isna(v):
            return None

        return v


class Column(BaseModel):
    """A Column node."""

    id: str = Field(..., description="The unique identifier for the column")
    name: str = Field(..., description="The name of the column")
    description: str | None = Field(default=None, description="The description of the column")
    embedding: list[float] | None = Field(
        default=None, description="The embedding of the column description"
    )
    type: str | None = Field(
        default=None,
        description="The data type of the column. Data types may be unavailable in source data such as query logs.",
    )
    nullable: bool = Field(default=True, description="Whether the column can be null")
    is_primary_key: bool = Field(default=False, description="Whether the column is a primary key")
    is_foreign_key: bool = Field(default=False, description="Whether the column is a foreign key")

    @field_validator("description", "type", mode="before")
    def validate_string_or_none(cls, v: str | None) -> str | None:
        """
        Validate that the string is string type or None.
        This will cast NaN values to None.
        """
        if isinstance(v, str):
            return v
        if v is None or isna(v):
            return None

        return v


class HasSchema(BaseModel):
    """
    A relationship between a database and a schema
    (Database)-[:HAS_SCHEMA]->(Schema).
    """

    database_id: str = Field(..., description="The unique identifier for the database")
    schema_id: str = Field(..., description="The unique identifier for the schema")


class HasTable(BaseModel):
    """
    A relationship between a schema and a table
    (Schema)-[:HAS_TABLE]->(Table).
    """

    schema_id: str = Field(..., description="The unique identifier for the schema")
    table_id: str = Field(..., description="The unique identifier for the table")


class HasColumn(BaseModel):
    """
    A relationship between a table and a column
    (Table)-[:HAS_COLUMN]->(Column).
    """

    table_id: str = Field(..., description="The unique identifier for the table")
    column_id: str = Field(..., description="The unique identifier for the column")


class References(BaseModel):
    """
    A relationship between two columns
    (Column)-[:REFERENCES]->(Column).
    """

    source_column_id: str = Field(..., description="The unique identifier for the source column")
    target_column_id: str = Field(..., description="The unique identifier for the target column")
    criteria: str | None = Field(
        default=None,
        description="The criteria for the references relationship. This is the join condition for the two columns.",
    )

    @field_validator("criteria", mode="before")
    def validate_string_or_none(cls, v: str | None) -> str | None:
        """
        Validate that the string is string type or None.
        This will cast NaN values to None.
        """
        if isinstance(v, str):
            return v
        if v is None or isna(v):
            return None

        return v
