"""Extract-stage typed dictionaries for the Unity Catalog schema connector.

These describe the flattened rows the extractor caches and the transformer
consumes. They are plain :class:`typing.TypedDict` shapes (not pydantic models):
the extractor builds them directly from the open Unity Catalog REST API payloads
(``CatalogInfo`` / ``SchemaInfo`` / ``TableInfo`` / ``ColumnInfo`` in the
``/api/2.1/unity-catalog`` spec).
"""

from __future__ import annotations

from typing import TypedDict


class CatalogInfo(TypedDict):
    """One row describing a Unity Catalog catalog (becomes a ``:Database`` node)."""

    catalog_name: str
    comment: str | None


class SchemaInfo(TypedDict):
    """One row describing a Unity Catalog schema (becomes a ``:Schema`` node)."""

    catalog_name: str
    schema_name: str
    comment: str | None


class TableInfo(TypedDict):
    """One row describing a Unity Catalog table or view (becomes a ``:Table`` node).

    Views fold into ``:Table``; ``table_type`` is retained for reference but is
    not modeled as a distinct node label.
    """

    catalog_name: str
    schema_name: str
    table_name: str
    table_type: str | None
    comment: str | None


class ColumnInfo(TypedDict):
    """One row describing a column, flattened from a table's embedded ``columns``."""

    catalog_name: str
    schema_name: str
    table_name: str
    column_name: str
    column_type: str | None
    nullable: bool
    comment: str | None


class UnityCatalogSchemaCache(TypedDict):
    """Cache of flattened extract rows the transformer reads.

    ``None`` means "not extracted" (e.g. excluded by a filter); an empty list
    means "extracted, nothing found".
    """

    catalog_info: list[CatalogInfo] | None
    schema_info: list[SchemaInfo] | None
    table_info: list[TableInfo] | None
    column_info: list[ColumnInfo] | None
