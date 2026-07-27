"""Shared source-agnostic tabular contract; populated in S1 (see GUIDE §5)."""

from .models import (
    ColumnRecord,
    DatabaseRecord,
    ForeignKeyRecord,
    NormalizedStructuralSchema,
    SchemaRecord,
    TableRecord,
)

__all__ = [
    "ColumnRecord",
    "DatabaseRecord",
    "ForeignKeyRecord",
    "NormalizedStructuralSchema",
    "SchemaRecord",
    "TableRecord",
]
