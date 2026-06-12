"""Conformance tests for OsiConnector.

Asserts conformance with the public connector standard defined in
``.claude/skills/neocarta-add-source-connector/connector-contract.md`` and codified in
``neocarta.connectors._base``.

OSI is a format connector (ingest + export), so it satisfies the stricter
:class:`FormatConnectorProtocol`.
"""

import importlib
import pathlib
from unittest.mock import MagicMock

import pytest

from neocarta.connectors._base import FormatConnectorProtocol
from neocarta.connectors.osi import OsiConnector
from neocarta.errors import StateError

PACKAGE = "neocarta.connectors.osi"


def _make_connector() -> OsiConnector:
    """Construct an OsiConnector with a mocked Neo4j driver."""
    return OsiConnector(neo4j_driver=MagicMock(), database_name="neo4j")


def test_conforms_to_format_connector_protocol():
    """OsiConnector is a format connector (ingest + export)."""
    assert isinstance(_make_connector(), FormatConnectorProtocol)


def test_has_public_stage_methods():
    """The standard public API + format export exists."""
    for name in ("extract", "transform", "load", "ingest", "export", "run"):
        assert callable(getattr(OsiConnector, name)), f"missing public method: {name}"


def test_run_emits_deprecation_warning():
    """run() must emit DeprecationWarning and delegate to ingest()."""
    connector = _make_connector()
    connector.ingest = MagicMock()
    with pytest.warns(DeprecationWarning, match="run"):
        connector.run("file.yaml")
    connector.ingest.assert_called_once()


def test_readme_present():
    """Every connector ships a README.md at its package root."""
    module = importlib.import_module(PACKAGE)
    package_dir = pathlib.Path(module.__file__).parent
    assert (package_dir / "README.md").exists()


def test_init_exports_are_minimal():
    """__init__.py exports only connector class + connector-specific warnings."""
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
