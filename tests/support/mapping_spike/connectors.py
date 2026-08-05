"""The per-connector mapping declarations — the S1.6 measurement.

Each declaration below replaces a hand-written ``transform.py``. The gate metric is these
declarations' size and hatch count against the file each replaces
(``docs/refactor/mapping-mechanism.md``), so keep them honest: no helper may hide mapping
logic that a real connector would have to write.

What is striking, and is the finding rather than the framework, is how little is left once
``normalized_schema/_vocabulary.py`` does the renaming. BigQuery's ``table_catalog`` /
``is_nullable`` / ``data_type``, and its whole foreign-key frame, bind with **zero** renames.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Any, NamedTuple

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

from .declaration import ConnectorMapping, SourceTable

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .declaration import ScopeContext

_COLUMN_ID_SEGMENTS = 4


def _container_path_from_column_id(row: dict[str, Any]) -> dict[str, Any]:
    """Recover a value row's container path from its precomputed ``column_id``.

    The ``pre_fold`` hatch, and a real gap rather than a fixture artefact: BigQuery's value
    frame carries only ``column_name`` / ``unique_value`` / ``column_id`` / ``value_id``
    (see the empty-frame column list in ``bigquery/schema/extract.py``), while
    ``ValueRecord`` is addressed by its full natural key. ``normalized_schema/README.md``
    records this as the projection the connector owes.

    Splitting is lossless *for identity* even though it is lossy for the display name: the
    segments come back already ``_normalize``d (``test-project-id`` → ``test_project_id``),
    and ``_normalize`` is idempotent, so regenerating ``value_id`` / ``column_id`` from them
    reproduces the extractor's ids exactly. ``Value`` carries no name, so nothing else reads
    them.

    Args:
        row: The raw value row.

    Returns:
        The row with canonical container segments set.

    Raises:
        ValueError: If ``column_id`` is not a four-segment path — better to fail loudly than
            to bind a truncated path and mint wrong ids.
    """
    segments = str(row["column_id"]).split(".")
    if len(segments) != _COLUMN_ID_SEGMENTS:
        message = f"expected a 4-segment column_id, got {row['column_id']!r}"
        raise ValueError(message)
    database_name, schema_name, table_name, _ = segments
    return {
        **row,
        "database_name": database_name,
        "schema_name": schema_name,
        "table_name": table_name,
    }


def _is_foreign_key(row: Mapping[str, Any]) -> bool:
    """Keep only true foreign-key constraints from a mixed constraint frame."""
    return row.get("constraint_type") == "FOREIGN KEY"


def _any_set(nodes: list[Any], field_name: str) -> bool:
    """Whether any node in a family has a non-``None`` value for ``field_name``."""
    return any(getattr(node, field_name) is not None for node in nodes)


def _omit_unset_properties(context: ScopeContext) -> list[str]:
    """Write an optional property only when some node in the family actually has one.

    The ``property_scope`` hatch in its whole-collection form, ported verbatim from
    ``jdbc/schema/transform.py``'s ``get_database_properties`` / ``get_column_properties``.
    It is a reduction over *every* built node — the properties written for the first node
    depend on the last — which is why property scope cannot be a per-row declaration and has
    to be a named hatch.

    This is the **D10** layer-1 obligation ``docs/refactor/merge-contract.md`` assigns to the
    connector/normalizer: writing ``is_primary_key: false`` for a source that simply exposes
    no key metadata would assert a falsehood, and writing ``description: null`` would erase
    another connector's description.

    Args:
        context: The family being scoped and every node already built for it.

    Returns:
        The property names to write, or an empty list when the family has no allowlist.
    """
    nodes = context.nodes
    if context.family == "database_nodes":
        return ["name", *(f for f in ("description", "service", "platform") if _any_set(nodes, f))]
    if context.family == "column_nodes":
        return [
            "name",
            "type",
            "nullable",
            *(f for f in ("description",) if _any_set(nodes, f)),
            # Truthiness, not "is not None" — matches the production reduction, where a
            # frame of all-False key flags is treated as "the source defined none".
            *(f for f in ("is_primary_key", "is_foreign_key") if any(getattr(n, f) for n in nodes)),
        ]
    return []


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


#: Ported from the eight ``_available_properties(...)`` call sites in ``csv/transform.py``.
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


def _csv_column_presence_scope(context: ScopeContext) -> list[str]:
    """Write only the properties whose CSV column is actually present.

    The ``property_scope`` hatch in its column-presence form, ported from
    ``csv/transform.py``'s ``_available_properties``. CSV files have an *open* schema — an
    optional column may or may not exist — so the written-property set is computed from the
    file's own header rather than declared. That is the same **D10** obligation JDBC solves by
    reducing over built nodes, reached from the opposite direction, and it is why this hatch
    has to accept a :class:`ScopeContext` rather than just the nodes.

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


# --- BigQuery schema (cluster A) -----------------------------------------------------------
#
# Replaces `neocarta/connectors/bigquery/schema/transform.py` (466 lines, 10 families).
# Every field binds through the ratified vocabulary with no renames: `project_id` and
# `table_catalog` are container synonyms, `data_type` and `is_nullable` are canonical, and
# the foreign-key frame's `constraint_catalog` / `constraint_schema` / `referenced_*` bind to
# the role-scoped FK aliases — which faithfully reproduces this connector's *existing*
# behaviour of deriving both endpoints from `constraint_*`, cross-dataset bug included.
# Parity means reproducing that; fixing it is its own ticket.
BIGQUERY_SCHEMA = ConnectorMapping(
    tables={
        "databases": SourceTable(
            record=DatabaseRecord,
            source="database_info",
            constants={"platform": "GCP", "service": "BIGQUERY"},
        ),
        "schemas": SourceTable(record=SchemaRecord, source="schema_info"),
        "tables": SourceTable(record=TableRecord, source="table_info"),
        "columns": SourceTable(record=ColumnRecord, source="column_info"),
        "values": SourceTable(
            record=ValueRecord,
            source="column_unique_values",
            project=_container_path_from_column_id,
        ),
        "foreign_keys": SourceTable(
            record=ForeignKeyRecord,
            source="column_references_info",
            row_filter=_is_foreign_key,
        ),
    },
    drop_self_references=True,
)


# --- JDBC schema via SchemaCrawler (external-runtime cluster) -------------------------------
#
# Replaces `neocarta/connectors/jdbc/schema/transform.py` (427 lines, 8 families). No
# `values` table — SchemaCrawler does not sample data — which the sparse contract (D10)
# expresses by simply leaving the table out.
#
# Every column is already canonical, including `type` and `nullable` (both ratified synonyms)
# and the whole `source_*` / `target_*` foreign-key frame. Its single shared `database_name`
# column binds to **both** FK endpoint roles, which is exactly the role-scoping case
# `docs/refactor/field-vocabulary.md` documents — so no rename here either.
#
# This connector is the reason the S1.6 proof needs more than Layer A: its property scope is a
# whole-collection reduction, and the harness only serializes an allowlist for transformers
# exposing `get_properties` — which this one does not (it has `get_database_properties` /
# `get_column_properties`). See `tests/unit/etl/mapping_spike/`.
JDBC_SCHEMA = ConnectorMapping(
    tables={
        "databases": SourceTable(record=DatabaseRecord, source="database_info"),
        "schemas": SourceTable(record=SchemaRecord, source="schema_info"),
        "tables": SourceTable(record=TableRecord, source="table_info"),
        "columns": SourceTable(record=ColumnRecord, source="column_info"),
        "foreign_keys": SourceTable(record=ForeignKeyRecord, source="column_references_info"),
    },
    drop_self_references=True,
    property_scope=_omit_unset_properties,
)


# --- CSV (format-connector cluster) --------------------------------------------------------
#
# Replaces the structural-core + values + glossary half of `neocarta/connectors/csv/transform.py`
# (574 lines, 20 families). The widest type surface of any connector, and the one whose CSV
# files are already written in the canonical vocabulary — so, again, no renames.
#
# Two things make it the most demanding member of the proof set:
#
# * `business_term_assignments` is fed by **two** frames. CSV pre-splits assignments by grain
#   into `column_tagged_with_info` / `table_tagged_with_info`; the contract models one table
#   whose grain is key-path depth. They concatenate here and the transform re-splits them,
#   which round-trips exactly because the table-grain frame carries no `column_name`.
# * Property scope is computed from each file's own header (`_csv_column_presence_scope`).
#
# **Documented exclusion:** CSV also emits the query families — `query_nodes`, `cte_nodes`,
# `uses_table_relationships`, `uses_column_relationships`, `defines_relationships` — which have
# **no normalized table at all**. That is deliberate, not a gap in this declaration: the query
# surface is a separate ingestion paradigm (GUIDE **D11**), listed under *"Not modelled (and
# why)"* in `normalized_schema/README.md`. The parity test therefore compares CSV on the
# families the tabular contract covers and asserts the exclusion explicitly, rather than
# quietly reporting a pass over a subset.
CSV_EXCLUDED_FAMILIES = (
    "query_nodes",
    "cte_nodes",
    "uses_table_relationships",
    "uses_column_relationships",
    "defines_relationships",
)

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
    property_scope=_csv_column_presence_scope,
)
