"""Fail-closed write boundary regression guard.

`run._project` is the single place that decides what reaches Neo4j. These
tests pin that a node DataFrame is projected to exactly
`contract.NODE_PROPERTIES[label]` in both the embedded and not-embedded
case, that the previously-leaked bookkeeping columns
(`embedding_text_hash` / `embedding_model` / `embedded_at`) and the
genuinely-leaked `table_schema` are stripped by construction, and that a
genuinely missing required property fails loudly. This is the test that
makes the leak class impossible to reintroduce silently.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from dbxcarta.spark.contract import NODE_PROPERTIES, NodeLabel
from dbxcarta.spark.run import _project

# Columns this refactor removes from the graph. None may survive _project.
_REMOVED = (
    "embedding_text",
    "embedding_text_hash",
    "embedding_model",
    "embedded_at",
    "embedding_error",
    "table_schema",
    "table_catalog",
)


_TYPES = {
    "id": "string",
    "name": "string",
    "catalog": "string",
    "schema": "string",
    "table": "string",
    "layer": "string",
    "platform": "string",
    "service": "string",
    "description": "string",
    "table_type": "string",
    "created": "string",
    "last_altered": "string",
    "type": "string",
    "nullable": "boolean",
    "is_primary_key": "boolean",
    "is_foreign_key": "boolean",
    "ordinal_position": "int",
    "value": "string",
    "count": "long",
    "last_run": "timestamp",
    "contract_version": "string",
    "embedding": "array<double>",
    "embedding_text": "string",
    "embedding_text_hash": "string",
    "embedding_model": "string",
    "embedded_at": "string",
    "embedding_error": "string",
    "table_schema": "string",
    "table_catalog": "string",
}


def _value_for(column: str) -> object:
    if column == "embedding":
        return [0.1, 0.2]
    if column == "last_run":
        return datetime(2026, 5, 17, tzinfo=UTC)
    if column in {"nullable", "is_primary_key", "is_foreign_key"}:
        return True
    if column in {"count", "ordinal_position"}:
        return 1
    if column == "contract_version":
        return "1.1"
    return column


def _node_df(local_spark, label: NodeLabel, *, embedded: bool):
    columns = [c for c in NODE_PROPERTIES[label] if embedded or c != "embedding"]
    columns.extend(_REMOVED)
    # Backtick every name: `schema` / `table` are SQL keywords and the
    # production path only ever uses the DataFrame API, never DDL parsing.
    schema = ", ".join(f"`{c}` {_TYPES[c]}" for c in columns)
    return local_spark.createDataFrame(
        [tuple(_value_for(c) for c in columns)],
        schema,
    )


@pytest.mark.parametrize("label", list(NodeLabel))
def test_project_embedded_node_is_exactly_declared(local_spark, label) -> None:
    """Embedded node: declared props + embedding + leaked helper/bookkeeping
    columns riding along. Output == declared tuple for every node label."""
    out = _project(_node_df(local_spark, label, embedded=True), label)
    assert tuple(out.columns) == NODE_PROPERTIES[label]
    for removed in _REMOVED:
        assert removed not in out.columns


@pytest.mark.parametrize("label", list(NodeLabel))
def test_project_not_embedded_node_omits_optional_embedding(
    local_spark,
    label,
) -> None:
    """Disabled-label path: no `embedding` column, builder's
    `embedding_text` still present. Output is declared minus `embedding`,
    with `embedding_text` stripped."""
    out = _project(_node_df(local_spark, label, embedded=False), label)
    expected = tuple(c for c in NODE_PROPERTIES[label] if c != "embedding")
    assert tuple(out.columns) == expected
    assert "embedding" not in out.columns
    assert "embedding_text" not in out.columns


def test_project_value_embedded_is_exactly_declared(local_spark) -> None:
    df = local_spark.createDataFrame(
        [
            (
                "c1.abc",
                "ACTIVE",
                42,
                "main",
                "sales",
                datetime(2026, 5, 17, tzinfo=UTC),
                "1.1",
                [0.3],
                "h",
                "ep",
                "2026",
                None,
                "ACTIVE",
            )
        ],
        "id string, value string, count long, catalog string, schema string,"
        " last_run timestamp, contract_version string,"
        " embedding array<double>, embedding_text_hash string,"
        " embedding_model string, embedded_at string, embedding_error string,"
        " embedding_text string",
    )
    out = _project(df, NodeLabel.VALUE)
    assert tuple(out.columns) == NODE_PROPERTIES[NodeLabel.VALUE]


def test_project_missing_required_property_raises(local_spark) -> None:
    """A genuinely missing declared column (not the optional `embedding`)
    is a contract violation and fails loudly rather than silently writing a
    partial node."""
    df = local_spark.createDataFrame([("only-id",)], "id string")
    with pytest.raises(RuntimeError, match="missing declared properties"):
        _project(df, NodeLabel.TABLE)
