"""Conformance tests for SnowflakeSchemaConnector.

Asserts conformance with the public connector standard defined in
``.claude/skills/neocarta-add-source-connector/connector-contract.md`` and codified in
``neocarta.connectors._base``.
"""

import importlib
import pathlib
from unittest.mock import MagicMock

import pytest

from neocarta.connectors._base import SourceConnectorProtocol
from neocarta.connectors.snowflake import SnowflakeSchemaConnector
from neocarta.errors import ConfigError, StateError

PACKAGE = "neocarta.connectors.snowflake"
SCHEMA_PACKAGE = "neocarta.connectors.snowflake.schema"


def _make_connector() -> SnowflakeSchemaConnector:
    """Construct a SnowflakeSchemaConnector with mocked external dependencies."""
    return SnowflakeSchemaConnector(
        connection=MagicMock(),
        database="test_database",
        neo4j_driver=MagicMock(),
    )


def test_conforms_to_source_connector_protocol():
    """SnowflakeSchemaConnector is a source connector."""
    assert isinstance(_make_connector(), SourceConnectorProtocol)


def test_has_public_stage_methods():
    """The standard public API (extract / transform / load / ingest / run) exists."""
    for name in ("extract", "transform", "load", "ingest", "run"):
        assert callable(getattr(SnowflakeSchemaConnector, name)), f"missing public method: {name}"


def test_run_emits_deprecation_warning():
    """run() must emit DeprecationWarning and delegate to ingest()."""
    connector = _make_connector()
    connector.ingest = MagicMock()
    with pytest.warns(DeprecationWarning, match="run"):
        connector.run("test_schema")
    connector.ingest.assert_called_once_with("test_schema")


def test_ingest_runs_stages_and_records_metadata():
    """ingest() runs extract -> transform -> load then records the graph metadata node."""
    connector = _make_connector()
    connector.extract = MagicMock()
    connector.transform = MagicMock()
    connector.load = MagicMock()
    connector.loader = MagicMock()
    connector.ingest("test_schema")
    connector.extract.assert_called_once_with("test_schema")
    connector.transform.assert_called_once_with()
    connector.load.assert_called_once_with()
    connector.loader.upsert_neocarta_graph_node.assert_called_once_with()


def test_readme_present():
    """Every connector ships a README.md at its package root."""
    module = importlib.import_module(PACKAGE)
    package_dir = pathlib.Path(module.__file__).parent
    assert (package_dir / "README.md").exists()


def test_init_exports_are_minimal():
    """__init__.py exports only connector classes / warnings (no Extractor/Transformer/Loader)."""
    module = importlib.import_module(PACKAGE)
    exported = getattr(module, "__all__", None)
    assert exported is not None, "__init__.py must define __all__"
    for name in exported:
        assert not name.endswith(("Extractor", "Transformer", "Loader")), (
            f"{name} should not be re-exported from {PACKAGE}.__init__.py"
        )


def test_init_exports_both_connectors():
    """The package exports both the schema and logs connectors."""
    module = importlib.import_module(PACKAGE)
    assert "SnowflakeSchemaConnector" in module.__all__
    assert "SnowflakeLogsConnector" in module.__all__


def test_schema_subpackage_exports_are_minimal():
    """The schema sub-package's own __init__.py exports only its connector class."""
    module = importlib.import_module(SCHEMA_PACKAGE)
    exported = getattr(module, "__all__", None)
    assert exported is not None, "schema/__init__.py must define __all__"
    assert "SnowflakeSchemaConnector" in exported
    for name in exported:
        assert not name.endswith(("Extractor", "Transformer", "Loader")), (
            f"{name} should not be re-exported from {SCHEMA_PACKAGE}.__init__.py"
        )


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


def test_close_leaves_injected_driver_open():
    """close() must not close the caller-owned Neo4j driver."""
    connector = _make_connector()
    connector.close()
    connector.neo4j_driver.close.assert_not_called()


def test_close_leaves_injected_connection_open():
    """close() must not close the caller-owned snowflake.connector connection."""
    connector = _make_connector()
    connector.close()
    connector.connection.close.assert_not_called()


def test_context_manager_exit_leaves_injected_driver_open():
    """Exiting the context manager must not close the caller-owned Neo4j driver."""
    connector = _make_connector()
    with connector:
        pass
    connector.neo4j_driver.close.assert_not_called()


def test_context_manager_exit_leaves_injected_connection_open():
    """Exiting the context manager must not close the caller-owned connection."""
    connector = _make_connector()
    with connector:
        pass
    connector.connection.close.assert_not_called()


def test_context_manager_exit_on_exception_leaves_driver_open():
    """An error inside the `with` block propagates and leaves the driver open."""
    connector = _make_connector()
    with pytest.raises(ValueError, match="boom"), connector:
        raise ValueError("boom")
    connector.neo4j_driver.close.assert_not_called()


def test_missing_connection_raises_config_error():
    """A missing connection is a configuration error."""
    with pytest.raises(ConfigError):
        SnowflakeSchemaConnector(
            connection=None, database="test_database", neo4j_driver=MagicMock()
        )


def test_missing_database_raises_config_error():
    """A missing database is a configuration error."""
    with pytest.raises(ConfigError):
        SnowflakeSchemaConnector(connection=MagicMock(), database="", neo4j_driver=MagicMock())


def test_missing_driver_raises_config_error():
    """A missing Neo4j driver is a configuration error."""
    with pytest.raises(ConfigError):
        SnowflakeSchemaConnector(
            connection=MagicMock(), database="test_database", neo4j_driver=None
        )


def test_extract_rejects_empty_schema():
    """extract() requires a schema name."""
    connector = _make_connector()
    with pytest.raises(ConfigError):
        connector.extract("")


def test_extract_rejects_double_quote_schema():
    """A malformed schema identifier fails fast and uniformly (any value_sample_limit)."""
    connector = _make_connector()
    with pytest.raises(ConfigError):
        connector.extract('bad"schema')
