"""Conformance tests for DatabricksSparkSchemaConnector.

Asserts conformance with the public connector standard defined in
``.claude/skills/neocarta-add-source-connector/connector-contract.md`` and codified in
``neocarta.connectors._base``.
"""

import importlib
import pathlib
from unittest.mock import MagicMock

import pytest

from neocarta.connectors._base import SourceConnectorProtocol
from neocarta.connectors.databricks import DatabricksSparkSchemaConnector

PACKAGE = "neocarta.connectors.databricks"


def test_conforms_to_source_connector_protocol():
    """DatabricksSparkSchemaConnector is a source connector."""
    assert isinstance(DatabricksSparkSchemaConnector(), SourceConnectorProtocol)


def test_has_public_stage_methods():
    """The standard public API (extract / transform / load / ingest / run) exists."""
    for name in ("extract", "transform", "load", "ingest", "run"):
        assert callable(getattr(DatabricksSparkSchemaConnector, name)), (
            f"missing public method: {name}"
        )


def test_run_emits_deprecation_warning():
    """run() must emit DeprecationWarning and delegate to ingest()."""
    connector = DatabricksSparkSchemaConnector()
    connector.ingest = MagicMock()
    with pytest.warns(DeprecationWarning, match="run"):
        connector.run()
    connector.ingest.assert_called_once()


def test_stage_methods_not_individually_addressable():
    """extract / transform / load raise NotImplementedError; ingest is the entrypoint.

    The Spark connector runs as a single job, so the stages are not exposed
    individually (unlike the in-process connectors).
    """
    connector = DatabricksSparkSchemaConnector()
    for name in ("extract", "transform", "load"):
        with pytest.raises(NotImplementedError):
            getattr(connector, name)()


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
