"""Flat information-schema container for normalized relational metadata."""

from typing import ClassVar

from pydantic import Field

from .base import NormalizedMetadata
from .records import (
    ColumnRecord,
    DatabaseRecord,
    ReferenceRecord,
    SchemaRecord,
    TableRecord,
    ValueRecord,
)


class InformationSchemaTable(NormalizedMetadata):
    """A flat catalog container of record lists mirroring ``INFORMATION_SCHEMA``.

    Hierarchy is implicit via shared name-parts rather than nesting, and foreign
    keys are flat rows. Empty construction yields six empty lists.
    """

    normalized_kind: ClassVar[str] = "information_schema"

    databases: list[DatabaseRecord] = Field(
        default_factory=list, description="The database (catalog) records"
    )
    schemas: list[SchemaRecord] = Field(
        default_factory=list, description="The schema (dataset) records"
    )
    tables: list[TableRecord] = Field(default_factory=list, description="The table records")
    columns: list[ColumnRecord] = Field(default_factory=list, description="The column records")
    references: list[ReferenceRecord] = Field(
        default_factory=list, description="The foreign-key reference rows"
    )
    values: list[ValueRecord] = Field(
        default_factory=list, description="The sampled column-value records"
    )
