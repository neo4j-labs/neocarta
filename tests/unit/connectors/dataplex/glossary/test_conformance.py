"""Conformance tests for DataplexGlossaryConnector.

Asserts conformance with the public connector standard defined in
``.claude/skills/neocarta-add-source-connector/connector-contract.md`` and codified in
``neocarta.connectors._base``.
"""

import importlib
import pathlib
from unittest.mock import MagicMock

import pytest

from neocarta.connectors._base import SourceConnectorProtocol
from neocarta.connectors.dataplex import DataplexGlossaryConnector
from neocarta.errors import StateError

PACKAGE = "neocarta.connectors.dataplex"


def _make_connector() -> DataplexGlossaryConnector:
    """Construct a DataplexGlossaryConnector with mocked external dependencies."""
    return DataplexGlossaryConnector(
        glossary_client=MagicMock(),
        project_id="test-project",
        project_number="123456",
        dataplex_location="us-central1",
        neo4j_driver=MagicMock(),
    )


def test_conforms_to_source_connector_protocol():
    """DataplexGlossaryConnector is a source connector."""
    assert isinstance(_make_connector(), SourceConnectorProtocol)


def test_has_public_stage_methods():
    """The standard public API (extract / transform / load / ingest / run) exists."""
    for name in ("extract", "transform", "load", "ingest", "run"):
        assert callable(getattr(DataplexGlossaryConnector, name)), f"missing public method: {name}"


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
    """__init__.py exports only connector classes (no Extractor/Transformer/Loader)."""
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


def test_context_manager_exit_leaves_injected_driver_open():
    """Exiting the context manager must not close the caller-owned Neo4j driver."""
    connector = _make_connector()
    with connector:
        pass
    connector.neo4j_driver.close.assert_not_called()


def test_driver_usable_across_repeated_context_blocks():
    """The caller's driver survives repeated context-managed use, ready for reuse."""
    connector = _make_connector()
    driver = connector.neo4j_driver
    with connector:
        pass
    with connector:
        pass
    driver.close.assert_not_called()


def test_context_manager_exit_on_exception_leaves_driver_open():
    """An error inside the `with` block propagates and leaves the driver open."""
    connector = _make_connector()
    with pytest.raises(ValueError, match="boom"), connector:
        raise ValueError("boom")
    connector.neo4j_driver.close.assert_not_called()
