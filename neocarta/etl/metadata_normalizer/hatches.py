"""Shared implementations of the two escape hatches most connectors use identically.

The hatch *list* stays closed at four (:mod:`declaration`); this module is about their
**implementations**. Two of the four are written the same way by more than one connector, so they
are parameterized here instead of copied:

- **``pre_fold``** — :func:`container_path_from`, for the recurring case of splitting a precomputed
  ``*_id`` back into the canonical container tokens the record is addressed by.
- **``property_scope``** — :func:`static_scope`, for a *constant* list per family, which is what a
  connector hard-coding ``properties_list`` at its ``load_*()`` call site is expressing.

Sharing them is the point of the S1.6 gate metric rather than a violation of it: ``hatch_usage``
still counts one use per declaration site, so the measurement is unchanged. The hatch forms that
are genuinely bespoke — JDBC's whole-collection reduction and CSV's column-presence filter — stay
hand-written next to the connector that needs them, because they are not the same operation with
different arguments.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from neocarta.errors import ConfigError

from .declaration import ScopeContext

#: A ``pre_fold`` hatch: one source row in, one source row out, before validation.
RowProjection = Callable[[dict[str, Any]], dict[str, Any]]


def container_path_from(
    id_field: str,
    fields: Sequence[str | None],
    *,
    id_segments: int | None = None,
) -> RowProjection:
    """Build a ``pre_fold`` that recovers a row's container path from a precomputed id.

    Several extractors compute a dotted graph id during extraction but do not carry the natural
    key it was built from — BigQuery, Databricks and Snowflake value frames are exactly
    ``[column_name, unique_value, column_id, value_id]``, and the query-log frames carry the
    generated ids and a SQL *alias* rather than the real container path. The record is addressed
    by its full natural key, so the connector owes that projection.

    Splitting is lossless **for identity**, which is the only thing that matters here: the
    segments come back already normalized (``test-project-id`` → ``test_project_id``) and
    ``generate_id``'s ``_normalize`` is idempotent, so regenerating an id from them reproduces
    the extractor's id exactly. It is lossy for a display name, which is why it is only ever
    applied to rows whose records carry no name.

    The split runs **right to left**, because only the trailing segment count is known: a database
    name legitimately contains dots (a domain-scoped GCP project is ``example.com:my-project``,
    and ``_normalize`` leaves ``.`` and ``:`` alone). A left-to-right split counts those as
    separators and rejects the row, aborting a connector that works today. A dot in a *trailing*
    segment — a column literally named ``addr.city`` — is still unrecoverable, and is the case the
    guard below exists to refuse loudly rather than mis-split.

    Only assign what the row does not already carry honestly. A frame that supplies a real
    ``project_id`` should bind *that*, not the normalized spelling recovered from an id, so pass
    ``None`` for a segment to skip it — the guard still checks the whole shape.

    Args:
        id_field: The row field holding the dotted id, e.g. ``"column_id"``.
        fields: The canonical field names to assign, positionally from the first segment.
            ``None`` skips that segment.
        id_segments: How many segments the id must have. Defaults to ``len(fields)``; pass a
            larger number when the id ends in a leaf the record does not need (a ``column_id``
            has four segments but a value row needs only its three container ones).

    Returns:
        A ``pre_fold`` projection.

    Raises:
        ConfigError: If ``id_segments`` is smaller than the number of fields to assign — the
            declaration itself is wrong, so it fails at import rather than per row.
    """
    expected = len(fields) if id_segments is None else id_segments
    if expected < len(fields):
        message = (
            f"{id_field!r} is declared with {expected} segments but {len(fields)} fields to "
            "assign; a container path cannot be longer than the id it comes from"
        )
        raise ConfigError(message)

    def project(row: dict[str, Any]) -> dict[str, Any]:
        # Split from the RIGHT. The trailing segments are the ones whose count is known; the
        # leading one is a database name, which legitimately contains dots — a domain-scoped GCP
        # project is `example.com:my-project`, and `generate_id`'s `_normalize` maps `-` and space
        # to `_` but leaves `.` and `:` alone. Splitting left-to-right counts those dots as
        # separators and rejects the row, which would abort the whole connector on a source the
        # hand-written transforms handle today.
        segments = str(row[id_field]).rsplit(".", expected - 1)
        if len(segments) != expected:
            message = (
                f"expected a {expected}-segment {id_field}, got {row[id_field]!r}; binding a "
                "truncated path would mint wrong ids"
            )
            raise ConfigError(message)
        assigned = {
            field: segment
            for field, segment in zip(fields, segments, strict=False)
            if field is not None
        }
        return {**row, **assigned}

    return project


def static_scope(scopes: Mapping[str, Sequence[str]]) -> Callable[[ScopeContext], list[str]]:
    """Build a ``property_scope`` hatch that writes a fixed property list per family.

    The third of the three property-scope semantics, and the one the S1.6 prototype did not port
    because neither JDBC nor CSV uses it: a connector hard-codes a literal ``properties_list`` at
    its ``load_*()`` call site. Expressing it here moves that decision into the declaration, which
    is the **D10** layer-1 obligation ``merge-contract.md`` assigns to the connector/normalizer and
    the one owner ``mapping-mechanism.md`` §8.4 asks #298 to establish.

    Args:
        scopes: Family accessor name (e.g. ``"column_nodes"``) → the properties to write. A
            family that is absent falls back to the loader's defaults, which an empty list means.

    Returns:
        A ``property_scope`` hatch.
    """

    def scope(context: ScopeContext) -> list[str]:
        return list(scopes.get(context.family, ()))

    return scope
