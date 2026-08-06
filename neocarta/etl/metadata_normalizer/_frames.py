"""The pandas adapter: the only module in this component that knows what a frame is.

Kept as a sibling of :mod:`binder` rather than folded into it, because the binder is written
against a general row source, not against frames. ``UnityCatalogSchemaExtractor`` caches
``list[TypedDict]`` while most connectors cache a ``DataFrame``, so a frame-first binder would
exclude that cluster by construction. Isolating the frame handling here is what lets the binder
accept both.

The narrower rule this placement protects is
[GUIDE](../../../docs/refactor/GUIDE.md) §4 *Model-Placement*: ``normalized_schema/`` is the
shared contract and names no frame library in its own source. This module sits one level above
it, so the dependency points the right way and the contract stays expressible without pandas.

Values are read **raw**. ``iterrows`` (not ``to_dict``) is deliberate: it is how today's
per-connector transforms read frames, and it yields the original cell objects — ``NaN``,
``numpy.bool_`` — which the contract's coercions in ``neocarta/data_model/_validators.py`` are
written to receive. Cleaning them here would bypass those validators and put a second owner on
value handling.
"""

from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import pandas as pd

#: What a connector may cache for one normalized table: a frame, a sequence of mappings, or
#: ``None`` for "this connector emits nothing here".
#:
#: A **sequence**, not a bare iterable: normalizing asks two questions about the same rows — what
#: records they bind to, and which columns they carried — so each collection is read twice. Every
#: cache in the repo is a frame or a list, so requiring re-readability costs nothing, where a
#: one-shot iterable would silently answer the second question with nothing.
RowSource = pd.DataFrame | Sequence[Mapping[str, Any]] | None


def as_rows(source: RowSource) -> Iterator[dict[str, Any]]:
    """Yield one plain dict per row of a cached source collection, in source order.

    Args:
        source: A frame, any iterable of mappings, or ``None``.

    Yields:
        One dict per row. Order is preserved: it is deterministic connector behaviour derived
        from ordered sources, and the Layer R goldens capture it, so reordering here would
        read as a parity failure rather than as a tidy-up.
    """
    if source is None:
        return
    if isinstance(source, pd.DataFrame):
        for _, row in source.iterrows():
            yield dict(row)
        return
    for row in source:
        yield dict(row)


def column_names(source: RowSource) -> tuple[str, ...]:
    """Return the field names a source collection carries, in source order.

    Read from the **source** rather than from the bound records because that is the question a
    column-presence ``property_scope`` hatch asks — "did the file supply this column?", not
    "did the contract keep the field?".

    Args:
        source: A frame, any iterable of mappings, or ``None``.

    Returns:
        The column names. A frame reports its declared columns even when it has no rows; any
        other iterable can only report the keys of its first row, and an empty one yields an
        empty tuple.
    """
    if isinstance(source, pd.DataFrame):
        return tuple(source.columns)
    return tuple(next(as_rows(source), {}))
