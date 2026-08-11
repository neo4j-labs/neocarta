"""Source rows → normalized records. The one piece the S1.x contract was missing.

S1.1-S1.5 shipped the normalized schema as a *contract*: 13 record models, a ratified field
vocabulary, coercions, a merge policy, an explicit-ID override. What it never shipped was a way
in — the only ingestion surface was ``Record.model_validate(mapping)``, one row at a time.

This module is that surface, and it is deliberately thin, because the renaming and coercion work
is **already done** by the records themselves. A raw BigQuery row
(``table_catalog``/``is_nullable="YES"``), a raw Unity Catalog ``ColumnInfo`` TypedDict
(``catalog_name``/``column_type``) and a raw Dataplex row
(``project_id``/``column_mode="REQUIRED"``) all validate into ``ColumnRecord`` with **zero**
renames, via ``validation_alias=AliasChoices(...)``. The binder adds only what no record can do
for itself: literal injection, a source-level row filter, and the ``pre_fold`` hatch.

Two boundaries it does not cross:

- **Values pass through raw.** ``NaN`` and ``numpy.bool_`` reach ``model_validate`` untouched,
  because the contract's coercions are written to receive exactly those. Cleaning them here
  would bypass the validators and put a second owner on value handling (GUIDE §4). The same rule
  covers blanks: folding ``""`` to ``None`` belongs to ``normalized_schema/_identity.py``.
- **Identity is left alone.** ``explicit_id`` is carried on the record and resolved downstream by
  ``etl/transform.resolve_id`` (**D6**, S1.4). The binder neither reads nor generates an id.
"""

from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from pydantic import BaseModel

from ._frames import RowSource, as_rows, column_names
from .declaration import ConnectorMapping, SourceTable

RecordT = TypeVar("RecordT", bound=BaseModel)


def bind(
    rows: RowSource,
    record: type[RecordT],
    *,
    constants: Mapping[str, Any] | None = None,
    project: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    row_filter: Callable[[Mapping[str, Any]], bool] | None = None,
) -> list[RecordT]:
    """Validate source rows into normalized records, in source order.

    The three optional steps apply in a fixed order — constants, then ``project``, then
    ``row_filter`` — so a ``pre_fold`` can derive the field a filter tests, and a filtered row is
    never validated and therefore need not even be a valid record.

    Args:
        rows: The source collection — a frame, an iterable of mappings, or ``None``.
        record: The normalized record class to validate into.
        constants: Source-level literals merged into each row *before* validation, so the
            record's own validators still see them. A value the row already carries wins.
        project: Optional ``pre_fold`` transform applied after ``constants``.
        row_filter: Optional predicate; a row is kept only when it returns true.

    Returns:
        The validated records, in source order.
    """
    constants = constants or {}
    records: list[RecordT] = []
    for row in as_rows(rows):
        prepared = {**constants, **row}
        if project is not None:
            prepared = project(prepared)
        if row_filter is not None and not row_filter(prepared):
            continue
        records.append(record.model_validate(prepared))
    return records


def fetch(source: Any, name: str) -> RowSource:
    """Read one named source collection off a dict-shaped cache or an extractor.

    Args:
        source: A dict-shaped cache (read by key) or an extractor (read by attribute).
        name: The cache key or accessor name.

    Returns:
        Whatever that name holds — a frame, an iterable of mappings, or ``None``.

    Note:
        Mappings are checked **first**, deliberately. Preferring attributes would resolve a cache
        key that collides with a ``dict`` method — ``{"items": [...]}`` — to the bound method
        rather than to the data, and the resulting failure would be far from its cause.
    """
    if isinstance(source, Mapping):
        return source[name]
    return getattr(source, name)


def bind_table(source: Any, table: SourceTable) -> list[BaseModel]:
    """Bind one declared table against a connector's extractor.

    Args:
        source: A dict-shaped cache (read by key) or an extractor (read by attribute).
        table: The declared binding.

    Returns:
        The validated records for that table, in source order — and, where a table is fed by
        several collections, in declared source order.
    """
    records: list[BaseModel] = []
    for name in table.sources:
        records.extend(
            bind(
                fetch(source, name),
                table.record,
                constants=table.constants,
                project=table.project,
                row_filter=table.row_filter,
            )
        )
    return records


def bind_all(source: Any, mapping: ConnectorMapping) -> dict[str, list[BaseModel]]:
    """Bind every declared table for a connector.

    Args:
        source: The connector's extractor, or its cache as a mapping.
        mapping: The connector's declaration.

    Returns:
        Normalized table name → its records, in declaration order. Only declared tables appear,
        which is how the sparse contract (**D10**) surfaces: an absent table means "this
        connector does not produce that", not "empty".
    """
    return {name: bind_table(source, table) for name, table in mapping.tables.items()}


def observed_columns(source: Any, mapping: ConnectorMapping) -> dict[str, tuple[str, ...]]:
    """Collect the field names each declared table's source rows actually carried.

    Only a ``property_scope`` hatch of the column-presence kind needs this — CSV decides which
    properties to write from which optional columns a file happens to have.

    Args:
        source: The connector's extractor, or its cache as a mapping.
        mapping: The connector's declaration.

    Returns:
        Normalized table name → its source field names, in source order and de-duplicated across
        a multi-source table. Tables whose source is empty map to an empty tuple.
    """
    observed: dict[str, tuple[str, ...]] = {}
    for name, table in mapping.tables.items():
        columns: list[str] = []
        for source_name in table.sources:
            columns.extend(
                column
                for column in column_names(fetch(source, source_name))
                if column not in columns
            )
        observed[name] = tuple(columns)
    return observed
