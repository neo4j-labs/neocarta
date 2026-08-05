"""Source rows → normalized records. The one piece the S1.x contract was missing.

S1.1-S1.5 shipped the normalized schema as a *contract*: 13 record models, a ratified field
vocabulary, coercions, a merge policy, an explicit-ID override. What it never shipped is a
way in — there is no ``normalize()`` or ``from_frame()`` anywhere under ``neocarta/``, and the
only ingestion surface is ``Record.model_validate(mapping)``, one row at a time.

This module is that surface, and it is deliberately thin, because the renaming and coercion
work is **already done** by the records themselves. A raw BigQuery row
(``table_catalog``/``is_nullable="YES"``), a raw Unity Catalog ``ColumnInfo`` TypedDict
(``catalog_name``/``column_type``) and a raw Dataplex row
(``project_id``/``column_mode="REQUIRED"``) all validate into ``ColumnRecord`` with **zero**
renames, via ``validation_alias=AliasChoices(...)``. The binder adds only what no record can
do for itself: literal injection, a source-level row filter, and the ``pre_fold`` hatch.

Two shape decisions matter. It accepts ``Iterable[Mapping[str, Any]]`` rather than a frame,
because ``UnityCatalogSchemaTransformer`` caches ``list[TypedDict]`` and a frame-first
signature would exclude that cluster by construction. And values are passed through **raw** —
``NaN``, ``numpy.bool_`` and numpy scalars reach ``model_validate`` untouched, because the
contract's coercions are written to receive exactly those; cleaning them here would bypass the
validators and put a second owner on value handling (GUIDE §4).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from pydantic import BaseModel

    from .declaration import ConnectorMapping, SourceTable

RecordT = TypeVar("RecordT", bound="BaseModel")


def as_rows(source: pd.DataFrame | Iterable[Mapping[str, Any]] | None) -> Iterator[dict[str, Any]]:
    """Yield one plain dict per row of a source collection, in source order.

    Args:
        source: A frame, any iterable of mappings, or ``None`` for "this connector emits
            nothing here".

    Yields:
        One dict per row. Order is preserved — the Layer A goldens capture emission order
        deliberately, so reordering here would read as a parity failure.
    """
    if source is None:
        return
    if isinstance(source, pd.DataFrame):
        # `iterrows` (not `to_dict`) keeps parity with how today's transforms read frames,
        # and yields the raw cell objects the record validators expect.
        for _, row in source.iterrows():
            yield dict(row)
        return
    for row in source:
        yield dict(row)


def bind(
    rows: pd.DataFrame | Iterable[Mapping[str, Any]] | None,
    record: type[RecordT],
    *,
    constants: Mapping[str, Any] | None = None,
    project: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    row_filter: Callable[[Mapping[str, Any]], bool] | None = None,
) -> list[RecordT]:
    """Validate source rows into normalized records, in source order.

    Args:
        rows: The source collection — a frame, an iterable of mappings, or ``None``.
        record: The normalized record class to validate into.
        constants: Source-level literals merged into each row *before* validation, so the
            record's own validators still see them. A value the row already carries wins — a
            source that reports its own platform is more specific than the declaration.
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


def _fetch(source: Any, name: str) -> Any:
    """Read one named source collection off a dict-shaped cache or an extractor.

    Mappings are checked **first**, deliberately. Preferring attributes would resolve a cache
    key that collides with a ``dict`` method — ``{"items": [...]}`` — to the bound method rather
    than the data, and the resulting failure would be far from its cause.
    """
    if isinstance(source, Mapping):
        return source[name]
    return getattr(source, name)


def _source_names(table: SourceTable) -> tuple[str, ...]:
    """Normalize a declared source to a tuple, so one and many read the same downstream."""
    return (table.source,) if isinstance(table.source, str) else table.source


def bind_table(source: Any, table: SourceTable) -> list[BaseModel]:
    """Bind one declared table against a connector's extractor.

    Args:
        source: A dict-shaped cache (read by key) or an extractor (read by attribute).
        table: The declared binding.

    Returns:
        The validated records for that table, in source order — and, where a table is fed by
        several frames, in declared frame order.
    """
    records: list[BaseModel] = []
    for name in _source_names(table):
        records.extend(
            bind(
                _fetch(source, name),
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
        source: The connector's extractor.
        mapping: The connector's declaration.

    Returns:
        Normalized table name → its records. Only declared tables appear, which is how the
        sparse contract (**D10**) surfaces: an absent table means "this connector does not
        produce that", not "empty".
    """
    return {name: bind_table(source, table) for name, table in mapping.tables.items()}


def observed_columns(source: Any, mapping: ConnectorMapping) -> dict[str, tuple[str, ...]]:
    """Collect the field names each declared table's source rows actually carried.

    Only a ``property_scope`` hatch of the column-presence kind needs this — CSV decides
    which properties to write from which optional columns a file happens to have. It is
    read from the **source** rather than the records because that is the question being
    asked: "did the file supply this?", not "did the contract keep it?".

    Args:
        source: The connector's extractor.
        mapping: The connector's declaration.

    Returns:
        Normalized table name → its source field names, in source order. Tables whose source
        is empty map to an empty tuple.
    """
    observed: dict[str, tuple[str, ...]] = {}
    for name, table in mapping.tables.items():
        columns: list[str] = []
        for source_name in _source_names(table):
            rows = _fetch(source, source_name)
            found = (
                tuple(rows.columns)
                if isinstance(rows, pd.DataFrame)
                else tuple(next(iter(as_rows(rows)), {}))
            )
            columns.extend(column for column in found if column not in columns)
        observed[name] = tuple(columns)
    return observed
