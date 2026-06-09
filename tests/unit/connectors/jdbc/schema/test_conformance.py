"""Conformance tests for JdbcSchemaConnector.

Asserts conformance with the public connector standard defined in
``.claude/skills/add-source-connector/connector-contract.md`` and codified in
``neocarta.connectors._base``.
"""

import importlib
import pathlib
from unittest.mock import MagicMock

import pytest

from neocarta.connectors._base import SourceConnectorProtocol
from neocarta.connectors.jdbc import JdbcSchemaConnector
from neocarta.errors import StateError

PACKAGE = "neocarta.connectors.jdbc"


def _make_connector() -> JdbcSchemaConnector:
    """Construct a JdbcSchemaConnector with mocked external dependencies.

    The Java availability probe is patched by the autouse ``_mock_java_check``
    fixture, so construction does not shell out to ``java``.
    """
    return JdbcSchemaConnector(
        jdbc_url="jdbc:postgresql://localhost:5432/testdb",
        jdbc_driver="org.postgresql.Driver",
        jdbc_driver_jar="schemacrawler-jars/postgresql.jar",
        schemacrawler_jar="schemacrawler-jars/schemacrawler.jar",
        neo4j_driver=MagicMock(),
    )


def test_conforms_to_source_connector_protocol():
    """JdbcSchemaConnector conforms to the SourceConnectorProtocol."""
    assert isinstance(_make_connector(), SourceConnectorProtocol)


def test_has_public_stage_methods():
    """The standard public API exists."""
    for name in ("extract", "transform", "load", "ingest", "run"):
        assert callable(getattr(JdbcSchemaConnector, name)), f"missing public method: {name}"


def test_run_emits_deprecation_warning():
    """run() must emit DeprecationWarning and delegate to ingest()."""
    connector = _make_connector()
    connector.ingest = MagicMock()
    with pytest.warns(DeprecationWarning, match="run"):
        connector.run()
    connector.ingest.assert_called_once()


def test_readme_present():
    """Every connector ships a README.md at its package root."""
    module = importlib.import_module(PACKAGE)
    package_dir = pathlib.Path(module.__file__).parent
    assert (package_dir / "README.md").exists()


def test_init_exports_are_minimal():
    """__init__.py exports only the connector class (no Extractor/Transformer/Loader)."""
    module = importlib.import_module(PACKAGE)
    exported = getattr(module, "__all__", None)
    assert exported is not None, "__init__.py must define __all__"
    for name in exported:
        assert not name.endswith(("Extractor", "Transformer", "Loader")), (
            f"{name} should not be re-exported from {PACKAGE}.__init__.py"
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
