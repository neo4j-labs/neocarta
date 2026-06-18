"""Unit tests for DatabricksGlossaryConnector orchestration + loader contract."""

from unittest.mock import MagicMock

import pytest

from neocarta.connectors.databricks import DatabricksGlossaryConnector
from neocarta.errors import ConfigError


def _connector(mock_workspace_client) -> DatabricksGlossaryConnector:
    connector = DatabricksGlossaryConnector(
        workspace_client=mock_workspace_client,
        neo4j_driver=MagicMock(),
    )
    connector.loader = MagicMock()
    return connector


def test_missing_workspace_client_raises_config_error():
    with pytest.raises(ConfigError):
        DatabricksGlossaryConnector(workspace_client=None, neo4j_driver=MagicMock())


def test_load_uses_property_lists_that_omit_undefined_props(mock_workspace_client):
    """Loader writes only populated properties — never NULL description/resource_path."""
    connector = _connector(mock_workspace_client)
    connector.extract()
    connector.transform()
    connector.load()

    glossary_kwargs = connector.loader.load_glossary_nodes.call_args.kwargs
    category_kwargs = connector.loader.load_category_nodes.call_args.kwargs
    business_term_kwargs = connector.loader.load_business_term_nodes.call_args.kwargs

    assert glossary_kwargs["properties_list"] == ["name", "resource_path"]
    assert category_kwargs["properties_list"] == ["name", "description", "resource_path"]
    # allowed-value terms carry only a name — no fabricated description/resource_path
    assert business_term_kwargs["properties_list"] == ["name"]


def test_ingest_records_graph_metadata(mock_workspace_client):
    connector = _connector(mock_workspace_client)
    connector.ingest()
    connector.loader.upsert_neocarta_graph_node.assert_called_once()


def test_ingest_forwards_include_system_tags(mock_workspace_client):
    connector = _connector(mock_workspace_client)
    connector.ingest(include_system_tags=True)
    # the system governed tag surfaces as a Category when requested
    assert any(
        node.name == "system.certification_status" for node in connector.transformer.category_nodes
    )
