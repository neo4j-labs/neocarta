"""Unit tests for DatabricksMetricsConnector orchestration (mocked loader)."""

from unittest.mock import MagicMock

import pytest

from neocarta.connectors.databricks.metrics import DatabricksMetricsConnector
from neocarta.errors import ConfigError

from .conftest import CATALOG, SCHEMA


def _connector(connection) -> DatabricksMetricsConnector:
    """A connector with a real extractor/transformer but a mocked loader."""
    connector = DatabricksMetricsConnector(
        connection=connection, catalog=CATALOG, neo4j_driver=MagicMock()
    )
    connector.loader = MagicMock()
    return connector


def test_ingest_drives_pipeline_and_records_metadata(mock_databricks_connection):
    """ingest() extracts -> transforms -> loads and records the graph metadata node."""
    connector = _connector(mock_databricks_connection)
    connector.ingest(schema=SCHEMA)

    loader = connector.loader
    loader.load_osi_semantic_model_nodes.assert_called_once()
    loader.load_osi_table_nodes.assert_called_once()
    loader.load_osi_column_nodes.assert_called_once()
    loader.load_metric_nodes.assert_called_once()
    loader.load_expression_nodes.assert_called_once()
    loader.load_osi_ai_context_nodes.assert_called_once()
    loader.load_business_term_nodes_by_name.assert_called_once()
    loader.load_has_metric_relationships.assert_called_once()
    loader.load_domain_has_table_relationships.assert_called_once()
    loader.load_has_aspect_relationships.assert_called_once()
    loader.load_osi_tagged_with_relationships.assert_called_once()
    loader.upsert_neocarta_graph_node.assert_called_once()


def test_load_omits_undefined_column_properties(mock_databricks_connection):
    """OsiColumn key/time-dimension flags are omitted from the load properties_list."""
    connector = _connector(mock_databricks_connection)
    connector.ingest(schema=SCHEMA)

    _, kwargs = connector.loader.load_osi_column_nodes.call_args
    assert kwargs["properties_list"] == ["name", "description", "label"]


def test_load_table_properties_omit_key_metadata(mock_databricks_connection):
    """OsiTable load writes only name/description/source (no primary_key/unique_keys)."""
    connector = _connector(mock_databricks_connection)
    connector.ingest(schema=SCHEMA)

    _, kwargs = connector.loader.load_osi_table_nodes.call_args
    assert kwargs["properties_list"] == ["name", "description", "source"]


def test_empty_schema_loads_only_metadata_node():
    """A schema with no metric views writes no OSI nodes but still records metadata."""
    from .conftest import make_connection

    connector = _connector(make_connection({}))
    connector.ingest(schema=SCHEMA)

    connector.loader.load_osi_semantic_model_nodes.assert_not_called()
    connector.loader.load_metric_nodes.assert_not_called()
    connector.loader.upsert_neocarta_graph_node.assert_called_once()


def test_missing_connection_raises_config_error():
    """A missing connection is a configuration error."""
    with pytest.raises(ConfigError):
        DatabricksMetricsConnector(connection=None, catalog=CATALOG, neo4j_driver=MagicMock())


def test_extract_rejects_empty_schema(mock_databricks_connection):
    """extract() requires a non-empty schema."""
    connector = _connector(mock_databricks_connection)
    with pytest.raises(ConfigError):
        connector.extract("")


def test_close_leaves_connection_and_driver_open(mock_databricks_connection):
    """close() never closes the caller-owned connection or driver."""
    connector = DatabricksMetricsConnector(
        connection=mock_databricks_connection, catalog=CATALOG, neo4j_driver=MagicMock()
    )
    connector.close()
    mock_databricks_connection.close.assert_not_called()
    connector.neo4j_driver.close.assert_not_called()
