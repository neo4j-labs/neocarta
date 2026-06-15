"""Unit tests for the Databricks connector's constraint/index DDL.

These exercise the pure label-selection logic and the `create_vector_indexes`
fan-out without a live Neo4j: the shared `create_vector_index` helper is patched
so the test asserts which labels are indexed, and at which dimension, in each
mode.
"""

from __future__ import annotations

from unittest.mock import patch

from neocarta.connectors.databricks.contract import NodeLabel
from neocarta.connectors.databricks.ingest.load.indexes import (
    _FULL_TEXT_INDEX_LABELS,
    _FULL_TEXT_PROPERTIES,
    _VECTOR_INDEX_LABELS,
    _vector_index_labels,
    bootstrap_constraints,
    create_full_text_indexes,
    create_vector_indexes,
)
from neocarta.connectors.databricks.settings import SparkIngestSettings

_STAGING = "/Volumes/cat/sch/vol/staging"


def test_external_indexes_all_eligible_labels() -> None:
    """External mode (no inline flags) indexes all four eligible labels."""
    settings = SparkIngestSettings(catalog="c")
    assert _vector_index_labels(settings, inline=False) == _VECTOR_INDEX_LABELS


def test_inline_indexes_only_enabled_labels() -> None:
    """Inline mode indexes only labels whose embedding flag is on, in order."""
    settings = SparkIngestSettings(
        catalog="c",
        include_embeddings_tables=True,
        include_embeddings_databases=True,
        embedding_staging_volume=_STAGING,
    )
    assert _vector_index_labels(settings, inline=True) == (
        NodeLabel.DATABASE,
        NodeLabel.TABLE,
    )


def test_value_label_never_indexed() -> None:
    """Value is never in the eligible set in either mode."""
    settings = SparkIngestSettings(catalog="c")
    assert NodeLabel.VALUE not in _VECTOR_INDEX_LABELS
    assert NodeLabel.VALUE not in _vector_index_labels(settings, inline=False)


def test_create_vector_indexes_uses_embedding_dimension() -> None:
    """Both modes create indexes at ``embedding_dimension``; external fans out to all four."""
    settings = SparkIngestSettings(catalog="c", embedding_dimension=1536)
    driver = object()

    with patch("neocarta.ingest.indexes.create_vector_index") as create_vector_index:
        create_vector_indexes(driver, settings, inline=False)

    created = {call.args[1]: call.args[2] for call in create_vector_index.call_args_list}
    assert created == {
        NodeLabel.DATABASE.value: 1536,
        NodeLabel.SCHEMA.value: 1536,
        NodeLabel.TABLE.value: 1536,
        NodeLabel.COLUMN.value: 1536,
    }


def test_create_vector_indexes_inline_skips_disabled_labels() -> None:
    """Inline mode only creates indexes for the enabled labels."""
    settings = SparkIngestSettings(
        catalog="c",
        include_embeddings_columns=True,
        embedding_dimension=1024,
        embedding_staging_volume=_STAGING,
    )
    driver = object()

    with patch("neocarta.ingest.indexes.create_vector_index") as create_vector_index:
        create_vector_indexes(driver, settings, inline=True)

    create_vector_index.assert_called_once_with(driver, NodeLabel.COLUMN.value, 1024)


def test_full_text_indexes_cover_schema_table_column() -> None:
    """One full-text index per label, over name/qualified_name/description.

    The labels and property set match what the MCP server's full-text Cypher
    queries by; Database is intentionally not full-text indexed.
    """
    assert _FULL_TEXT_INDEX_LABELS == (
        NodeLabel.SCHEMA,
        NodeLabel.TABLE,
        NodeLabel.COLUMN,
    )
    assert _FULL_TEXT_PROPERTIES == ("name", "qualified_name", "description")
    assert NodeLabel.DATABASE not in _FULL_TEXT_INDEX_LABELS

    driver = object()

    with patch("neocarta.ingest.indexes.create_full_text_index") as create_full_text_index:
        create_full_text_indexes(driver)

    created = {
        tuple(call.kwargs["node_labels"]): tuple(call.kwargs["property_names"])
        for call in create_full_text_index.call_args_list
    }
    assert created == {
        (NodeLabel.SCHEMA.value,): ("name", "qualified_name", "description"),
        (NodeLabel.TABLE.value,): ("name", "qualified_name", "description"),
        (NodeLabel.COLUMN.value,): ("name", "qualified_name", "description"),
    }


def test_bootstrap_constraints_creates_full_text_indexes() -> None:
    """The full-text indexes are wired into the connector's index bootstrap.

    Guards against the bootstrap silently dropping the full-text step: keyword
    search would break with no other test failing.
    """
    driver = object()

    with (
        patch("neocarta.ingest.utils.write_neo4j_constraints"),
        patch("neocarta.ingest.indexes.create_range_index"),
        patch(
            "neocarta.connectors.databricks.ingest.load.indexes.create_full_text_indexes"
        ) as create_full_text_indexes_mock,
    ):
        bootstrap_constraints(driver)

    create_full_text_indexes_mock.assert_called_once_with(driver)
