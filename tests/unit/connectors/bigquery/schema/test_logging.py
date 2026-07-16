"""Logging behaviour for the BigQuery schema extractor and connector."""

import logging
from unittest.mock import MagicMock

from neocarta.connectors.bigquery.schema.connector import BigQuerySchemaConnector

_EXTRACT_LOGGER = "neocarta.connectors.bigquery.schema.extract"
_CONNECTOR_LOGGER = "neocarta.connectors.bigquery.schema.connector"


def test_extract_method_logs_under_module_logger(bigquery_extractor, caplog):
    """A decorated extractor method logs a one-line summary under its module logger."""
    with caplog.at_level(logging.INFO, logger=_EXTRACT_LOGGER):
        bigquery_extractor.extract_database_info()

    records = [r for r in caplog.records if r.name == _EXTRACT_LOGGER]
    assert records, "expected an INFO record under the extractor module logger"
    message = records[0].getMessage()
    assert "rows" in message
    # No SQL is ever logged.
    assert "SELECT" not in message
    assert "INFORMATION_SCHEMA" not in message


def test_transform_phase_logs_per_type_counts(
    mock_bigquery_client, bigquery_extractor_with_cache, caplog
):
    """transform() logs a per-type produced-object count and never logs SQL."""
    connector = BigQuerySchemaConnector(
        client=mock_bigquery_client,
        project_id="test-project-id",
        neo4j_driver=MagicMock(),
    )
    # Drive transform() off a pre-populated extractor cache.
    connector.extractor = bigquery_extractor_with_cache
    connector._extracted = True

    with caplog.at_level(logging.INFO, logger=_CONNECTOR_LOGGER):
        connector.transform()

    messages = [r.getMessage() for r in caplog.records if r.name == _CONNECTOR_LOGGER]
    assert any("Transformed 4 columns" in m for m in messages)
    assert any("Transformed 2 tables" in m for m in messages)
    assert all("SELECT" not in m for m in messages)
