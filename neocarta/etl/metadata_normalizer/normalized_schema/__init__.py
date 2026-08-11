"""Shared source-agnostic tabular contract; populated in S1 (see GUIDE §5)."""

from .facets import (
    BusinessTermAssignmentRecord,
    BusinessTermRecord,
    CategoryRecord,
    GlossaryRecord,
    GovernanceTagKeyRecord,
    GovernanceTagValueRecord,
    LineageRecord,
    ValueRecord,
)
from .models import (
    ColumnRecord,
    DatabaseRecord,
    ForeignKeyRecord,
    NormalizedStructuralSchema,
    SchemaRecord,
    TableRecord,
)

__all__ = [
    "BusinessTermAssignmentRecord",
    "BusinessTermRecord",
    "CategoryRecord",
    "ColumnRecord",
    "DatabaseRecord",
    "ForeignKeyRecord",
    "GlossaryRecord",
    "GovernanceTagKeyRecord",
    "GovernanceTagValueRecord",
    "LineageRecord",
    "NormalizedStructuralSchema",
    "SchemaRecord",
    "TableRecord",
    "ValueRecord",
]
