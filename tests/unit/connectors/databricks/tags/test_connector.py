"""Unit tests for DatabricksTagsConnector orchestration + loader contract."""

from unittest.mock import MagicMock

import pytest

from neocarta.connectors.databricks import DatabricksTagsConnector
from neocarta.errors import ConfigError

from .conftest import _tag_policy


def _connector(mock_workspace_client) -> DatabricksTagsConnector:
    connector = DatabricksTagsConnector(
        workspace_client=mock_workspace_client,
        neo4j_driver=MagicMock(),
    )
    connector.loader = MagicMock()
    return connector


def test_missing_workspace_client_raises_config_error():
    with pytest.raises(ConfigError):
        DatabricksTagsConnector(workspace_client=None, neo4j_driver=MagicMock())


def test_load_uses_property_lists_that_omit_undefined_props(mock_workspace_client):
    """Loader writes only populated properties — never NULL description on bare values."""
    connector = _connector(mock_workspace_client)
    connector.extract()
    connector.transform()
    connector.load()

    key_kwargs = connector.loader.load_governance_tag_key_nodes.call_args.kwargs
    value_kwargs = connector.loader.load_governance_tag_value_nodes.call_args.kwargs

    assert key_kwargs["properties_list"] == ["name", "description"]
    # allowed-value nodes carry only a name — no fabricated description
    assert value_kwargs["properties_list"] == ["name"]
    connector.loader.load_has_value_option_relationships.assert_called_once()


def test_ingest_records_graph_metadata(mock_workspace_client):
    connector = _connector(mock_workspace_client)
    connector.ingest()
    connector.loader.upsert_neocarta_graph_node.assert_called_once()


def test_ingest_forwards_include_system_tags(mock_workspace_client):
    connector = _connector(mock_workspace_client)
    connector.ingest(include_system_tags=True)
    # the system governed tag surfaces as a GovernanceTagKey when requested
    assert any(
        node.name == "system.certification_status"
        for node in connector.transformer.governance_tag_key_nodes
    )


def test_default_excludes_platform_tags(mock_workspace_client):
    """By default a class.* platform tag is dropped while a user tag is kept."""
    mock_workspace_client.tag_policies.list_tag_policies.return_value = [
        _tag_policy("department", "Owning department", "tp-dep", ["finance"]),
        _tag_policy("class.pii", "classification", "tp-class", ["high"]),
    ]
    connector = _connector(mock_workspace_client)
    connector.extract()
    connector.transform()
    assert {n.name for n in connector.transformer.governance_tag_key_nodes} == {"department"}


def test_system_prefixes_param_forwarded_to_extractor(mock_workspace_client):
    """A custom system_prefixes set is honoured (here: empty → nothing excluded)."""
    mock_workspace_client.tag_policies.list_tag_policies.return_value = [
        _tag_policy("class.pii", "classification", "tp-class", ["high"]),
    ]
    connector = DatabricksTagsConnector(
        workspace_client=mock_workspace_client,
        neo4j_driver=MagicMock(),
        system_prefixes=(),
    )
    connector.loader = MagicMock()
    connector.extract()
    connector.transform()
    assert {n.name for n in connector.transformer.governance_tag_key_nodes} == {"class.pii"}
