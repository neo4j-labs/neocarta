"""Conformance tests for SnowflakeLogsConnector.

Asserts conformance with the public connector standard defined in
``.claude/skills/neocarta-add-source-connector/connector-contract.md`` and codified in
``neocarta.connectors._base``.
"""

from unittest.mock import MagicMock

import pytest

from neocarta.connectors._base import SourceConnectorProtocol
from neocarta.connectors.snowflake import SnowflakeLogsConnector
from neocarta.errors import ConfigError, StateError


def _make_connector() -> SnowflakeLogsConnector:
    """Construct a SnowflakeLogsConnector with mocked external dependencies."""
    return SnowflakeLogsConnector(
        connection=MagicMock(),
        database="test_database",
        neo4j_driver=MagicMock(),
    )


def test_conforms_to_source_connector_protocol():
    """SnowflakeLogsConnector is a source connector."""
    assert isinstance(_make_connector(), SourceConnectorProtocol)


def test_has_public_stage_methods():
    """The standard public API (extract / transform / load / ingest / run) exists."""
    for name in ("extract", "transform", "load", "ingest", "run"):
        assert callable(getattr(SnowflakeLogsConnector, name)), f"missing public method: {name}"


def test_run_emits_deprecation_warning():
    """run() must emit DeprecationWarning and delegate to ingest()."""
    connector = _make_connector()
    connector.ingest = MagicMock()
    with pytest.warns(DeprecationWarning, match="run"):
        connector.run()
    connector.ingest.assert_called_once()


def test_ingest_runs_stages_and_records_metadata():
    """ingest() runs extract -> transform -> load then records the graph metadata node."""
    connector = _make_connector()
    connector.extract = MagicMock()
    connector.transform = MagicMock()
    connector.load = MagicMock()
    connector.loader = MagicMock()
    connector.ingest(schema="test_schema", limit=10)
    connector.extract.assert_called_once()
    connector.transform.assert_called_once_with()
    connector.load.assert_called_once_with()
    connector.loader.upsert_neocarta_graph_node.assert_called_once_with()


def test_transform_before_extract_raises_state_error():
    """Calling transform() without a prior extract() raises StateError."""
    connector = _make_connector()
    with pytest.raises(StateError):
        connector.transform()


def test_load_before_transform_raises_state_error():
    """Calling load() without a prior transform() raises StateError."""
    connector = _make_connector()
    with pytest.raises(StateError):
        connector.load()


def test_context_manager_returns_self():
    """The connector is usable as a context manager and yields itself."""
    connector = _make_connector()
    with connector as ctx:
        assert ctx is connector


def test_close_leaves_injected_driver_and_connection_open():
    """close() must not close the caller-owned Neo4j driver or connection."""
    connector = _make_connector()
    connector.close()
    connector.neo4j_driver.close.assert_not_called()
    connector.connection.close.assert_not_called()


def test_context_manager_exit_leaves_injected_resources_open():
    """Exiting the context manager must not close the caller-owned driver/connection."""
    connector = _make_connector()
    with connector:
        pass
    connector.neo4j_driver.close.assert_not_called()
    connector.connection.close.assert_not_called()


def test_missing_connection_raises_config_error():
    """A missing connection is a configuration error."""
    with pytest.raises(ConfigError):
        SnowflakeLogsConnector(connection=None, database="test_database", neo4j_driver=MagicMock())


def test_missing_database_raises_config_error():
    """A missing database is a configuration error."""
    with pytest.raises(ConfigError):
        SnowflakeLogsConnector(connection=MagicMock(), database="", neo4j_driver=MagicMock())


def test_missing_driver_raises_config_error():
    """A missing Neo4j driver is a configuration error."""
    with pytest.raises(ConfigError):
        SnowflakeLogsConnector(connection=MagicMock(), database="test_database", neo4j_driver=None)
