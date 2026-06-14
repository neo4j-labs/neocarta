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
    _VECTOR_INDEX_LABELS,
    _vector_index_labels,
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
