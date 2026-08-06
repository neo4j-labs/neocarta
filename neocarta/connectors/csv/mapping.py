"""The CSV format connector's normalized-schema mapping declaration.

Replaces the structural-core + values + glossary half of [`transform.py`](transform.py) (574
lines, 20 families). The widest type surface of any connector, and the one whose files are
already written in the canonical vocabulary — so, again, no renames.

Two things make it the most demanding member of the S1.6 proof set:

* ``business_term_assignments`` is fed by **two** collections. CSV pre-splits assignments by grain
  into ``column_tagged_with_info`` / ``table_tagged_with_info``; the contract models one table
  whose grain is key-path depth. They concatenate here and the transform re-splits them, which
  round-trips exactly because the table-grain frame carries no ``column_name``.
* Property scope is computed from each file's own header, because a CSV has an *open* schema.

**Documented exclusion.** CSV also emits the query families — ``query_nodes``, ``cte_nodes``,
``uses_table_relationships``, ``uses_column_relationships``, ``defines_relationships`` — which
have **no normalized table at all**. That is deliberate, not a gap in this declaration: the query
surface is a separate ingestion paradigm (**D11**), listed under *"Not modelled (and why)"* in
``normalized_schema/README.md``.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import NamedTuple

from neocarta.etl.metadata_normalizer import ConnectorMapping, ScopeContext, SourceTable
from neocarta.etl.metadata_normalizer.normalized_schema import (
    BusinessTermAssignmentRecord,
    BusinessTermRecord,
    CategoryRecord,
    ColumnRecord,
    DatabaseRecord,
    ForeignKeyRecord,
    GlossaryRecord,
    SchemaRecord,
    TableRecord,
    ValueRecord,
)

#: Families this connector emits that the tabular contract does not model (**D11**). The parity
#: suite asserts the uncovered set is a *subset* of this, so a new uncovered family is caught while
#: a stale entry here would not be — hence only the three ``CSVTransformer`` actually exposes are
#: listed. The wider query surface (``cte_nodes``, ``defines_relationships``) belongs to the
#: query-log paradigm, which this connector does not produce.
CSV_EXCLUDED_FAMILIES = (
    "query_nodes",
    "uses_table_relationships",
    "uses_column_relationships",
)


class _CsvScope(NamedTuple):
    """One family's CSV property projection.

    Attributes:
        exclude: Parent-scope key columns that belong to an ancestor node, not this one.
        rename: CSV column → model property.
        force: Properties that must appear even when no column of that name does (because the
            column reaching them is renamed).
    """

    exclude: tuple[str, ...] = ()
    rename: Mapping[str, str] = MappingProxyType({})
    force: tuple[str, ...] = ()


#: Ported from the eight ``_available_properties(...)`` call sites in ``transform.py``.
_CSV_SCOPE: dict[str, _CsvScope] = {
    "database_nodes": _CsvScope(rename={"database_name": "name"}),
    "schema_nodes": _CsvScope(("database_name",), {"schema_name": "name"}),
    "table_nodes": _CsvScope(("database_name", "schema_name"), {"table_name": "name"}),
    "column_nodes": _CsvScope(
        ("database_name", "schema_name", "table_name"),
        {"column_name": "name", "data_type": "type", "is_nullable": "nullable"},
    ),
    "value_nodes": _CsvScope(
        ("database_name", "schema_name", "table_name", "column_name"), force=("value",)
    ),
    "glossary_nodes": _CsvScope(("glossary_name",), force=("name",)),
    "category_nodes": _CsvScope(("glossary_name", "category_name"), force=("name",)),
    "business_term_nodes": _CsvScope(
        ("glossary_name", "category_name", "term_name"), force=("name",)
    ),
}


def _column_presence_scope(context: ScopeContext) -> list[str]:
    """Write only the properties whose CSV column is actually present.

    The ``property_scope`` hatch in its column-presence form, ported from ``_available_properties``.
    CSV files have an *open* schema — an optional column may or may not exist — so the
    written-property set is computed from the file's own header rather than declared. That is the
    same **D10** obligation JDBC solves by reducing over built nodes, reached from the opposite
    direction, and it is why this hatch has to accept a :class:`ScopeContext` rather than just the
    nodes.

    Args:
        context: The family being scoped, its nodes, and its source column names.

    Returns:
        The property names to write, or an empty list for families with no allowlist.
    """
    scope = _CSV_SCOPE.get(context.family)
    if scope is None:
        return []
    dropped = {"id", *scope.exclude}
    # `*_id` columns are structural identity computed during extraction, never properties.
    properties = [
        scope.rename.get(column, column)
        for column in context.source_columns
        if column not in dropped and not column.endswith("_id")
    ]
    properties.extend(name for name in scope.force if name not in properties)
    return properties


CSV = ConnectorMapping(
    tables={
        "databases": SourceTable(record=DatabaseRecord, source="database_info"),
        "schemas": SourceTable(record=SchemaRecord, source="schema_info"),
        "tables": SourceTable(record=TableRecord, source="table_info"),
        "columns": SourceTable(record=ColumnRecord, source="column_info"),
        "values": SourceTable(record=ValueRecord, source="value_info"),
        "foreign_keys": SourceTable(record=ForeignKeyRecord, source="column_references_info"),
        "glossaries": SourceTable(record=GlossaryRecord, source="glossary_info"),
        "categories": SourceTable(record=CategoryRecord, source="category_info"),
        "business_terms": SourceTable(record=BusinessTermRecord, source="business_term_info"),
        "business_term_assignments": SourceTable(
            record=BusinessTermAssignmentRecord,
            source=("column_tagged_with_info", "table_tagged_with_info"),
        ),
    },
    property_scope=_column_presence_scope,
)
