"""The JDBC (SchemaCrawler) schema connector's normalized-schema mapping declaration.

Replaces the mapping half of [`transform.py`](transform.py) (427 lines, 8 families). There is no
``values`` table — SchemaCrawler samples no data — which the sparse contract (**D10**) expresses
by simply leaving the table out rather than by emitting an empty one.

Every column is already canonical, including ``type`` and ``nullable`` (both ratified synonyms)
and the whole ``source_*`` / ``target_*`` foreign-key frame. Its single shared ``database_name``
column binds to **both** FK endpoint roles, which is exactly the role-scoping case
[field-vocabulary.md](../../../../docs/refactor/field-vocabulary.md) documents — so no rename
here either.

This connector is why the S1.6 proof needed more than the graph-level harness: its property scope
is a whole-collection reduction, and the harness only serializes an allowlist for transformers
exposing ``get_properties``, which this one does not.
"""

from typing import Any

from neocarta.etl.metadata_normalizer import (
    ConnectorMapping,
    ScopeContext,
    SourceTable,
)
from neocarta.etl.metadata_normalizer.normalized_schema import (
    ColumnRecord,
    DatabaseRecord,
    ForeignKeyRecord,
    SchemaRecord,
    TableRecord,
)


def _any_set(nodes: list[Any], field_name: str) -> bool:
    """Whether any node in a family has a non-``None`` value for ``field_name``."""
    return any(getattr(node, field_name) is not None for node in nodes)


def _omit_unset_properties(context: ScopeContext) -> list[str]:
    """Write an optional property only when some node in the family actually has one.

    The ``property_scope`` hatch in its whole-collection form, ported verbatim from this
    connector's ``get_database_properties`` / ``get_column_properties``. It is a reduction over
    *every* built node — the properties written for the first node depend on the last — which is
    why property scope cannot be a per-row declaration and has to be a named hatch. It is left
    hand-written rather than shared because it is not the constant-list form other connectors use;
    it is genuinely this source's logic.

    This is the **D10** layer-1 obligation
    [merge-contract.md](../../../../docs/refactor/merge-contract.md) assigns to the
    connector/normalizer: writing ``is_primary_key: false`` for a source that exposes no key
    metadata would assert a falsehood, and writing ``description: null`` would erase another
    connector's description.

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
            # Truthiness, not "is not None" — matches the production reduction, where a frame of
            # all-False key flags is treated as "the source defined none".
            *(f for f in ("is_primary_key", "is_foreign_key") if any(getattr(n, f) for n in nodes)),
        ]
    return []


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
