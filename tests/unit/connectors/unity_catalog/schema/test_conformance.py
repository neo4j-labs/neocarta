"""Conformance tests for UnityCatalogSchemaConnector.

Asserts conformance with the public connector standard defined in
``.claude/skills/neocarta-add-source-connector/connector-contract.md`` and codified in
``neocarta.connectors._base``.
"""

import importlib
import pathlib
from unittest.mock import MagicMock

import pytest

from neocarta.connectors._base import SourceConnectorProtocol
from neocarta.connectors.unity_catalog import UnityCatalogSchemaConnector
from neocarta.errors import StateError

PACKAGE = "neocarta.connectors.unity_catalog"


def _make_connector() -> UnityCatalogSchemaConnector:
    """Construct a UnityCatalogSchemaConnector with mocked external dependencies."""
    return UnityCatalogSchemaConnector(
        base_url="https://uc.example.com/api/2.1/unity-catalog",
        neo4j_driver=MagicMock(),
    )


def test_conforms_to_source_connector_protocol():
    """UnityCatalogSchemaConnector conforms to the SourceConnectorProtocol."""
    assert isinstance(_make_connector(), SourceConnectorProtocol)


def test_has_public_stage_methods():
    """The standard public API exists."""
    for name in ("extract", "transform", "load", "ingest", "run"):
        assert callable(getattr(UnityCatalogSchemaConnector, name)), (
            f"missing public method: {name}"
        )


def test_run_emits_deprecation_warning():
    """run() must emit DeprecationWarning and delegate to ingest()."""
    connector = _make_connector()
    connector.ingest = MagicMock()
    with pytest.warns(DeprecationWarning, match="run"):
        connector.run("main")
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


def test_run_forwards_args_to_ingest():
    """run() forwards its catalog/schemas/filters through to ingest()."""
    connector = _make_connector()
    connector.ingest = MagicMock()
    with pytest.warns(DeprecationWarning, match="run"):
        connector.run("main")
    connector.ingest.assert_called_once_with(
        "main", None, include_nodes=None, include_relationships=None
    )


def test_close_closes_http_client():
    """close() releases the extractor's owned HTTP client."""
    connector = _make_connector()
    connector.extractor._client = MagicMock()
    connector.close()
    connector.extractor._client.close.assert_called_once()


def test_context_manager_closes_http_client():
    """Using the connector as a context manager closes the HTTP client on exit."""
    connector = _make_connector()
    connector.extractor._client = MagicMock()
    with connector as ctx:
        assert ctx is connector
    connector.extractor._client.close.assert_called_once()
