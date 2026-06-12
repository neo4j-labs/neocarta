"""Unit tests for JdbcSchemaConnector orchestration."""

from unittest.mock import MagicMock, patch

import pytest

from neocarta.connectors.jdbc import JdbcSchemaConnector
from neocarta.errors import ConfigError

SUBPROCESS_RUN = "neocarta.connectors.jdbc.schema.extract.subprocess.run"


def _make_connector(**overrides):
    """Build a connector with dummy config (java check patched by conftest)."""
    kwargs = {
        "jdbc_url": "jdbc:postgresql://localhost:5432/neocarta_test",
        "jdbc_driver": "org.postgresql.Driver",
        "jdbc_driver_jar": "schemacrawler-jars/postgresql.jar",
        "schemacrawler_jar": "schemacrawler-jars/schemacrawler.jar",
        "neo4j_driver": MagicMock(),
    }
    kwargs.update(overrides)
    return JdbcSchemaConnector(**kwargs)


def test_source_database_name_derived_from_url():
    """The source DB name defaults to the parsed JDBC URL path."""
    assert _make_connector().source_database_name == "neocarta_test"


def test_explicit_source_database_name_overrides_url():
    """An explicit source_database_name is used even for unparseable URLs."""
    connector = _make_connector(
        jdbc_url="jdbc:oracle:thin:@host:1521:ORCL",
        source_database_name="warehouse",
    )
    assert connector.source_database_name == "warehouse"


def test_unparseable_url_without_explicit_name_raises():
    """A URL with no path-based DB and no explicit name raises ConfigError."""
    with pytest.raises(ConfigError, match="source database name"):
        _make_connector(jdbc_url="jdbc:oracle:thin:@host:1521:ORCL")


def test_extract_then_transform_populates_all_nodes(golden_catalog_json):
    """connector.extract() → transform() wires the extractor caches to the transformer."""
    connector = _make_connector()
    completed = MagicMock(returncode=0, stdout=golden_catalog_json, stderr="")
    with patch(SUBPROCESS_RUN, return_value=completed):
        connector.extract()
    connector.transform()

    transformer = connector.transformer
    assert len(transformer.database_nodes) == 1
    assert len(transformer.schema_nodes) == 2
    assert len(transformer.table_nodes) == 3
    assert len(transformer.column_nodes) == 7
    assert len(transformer.has_schema_relationships) == 2
    assert len(transformer.has_table_relationships) == 3
    assert len(transformer.has_column_relationships) == 7
    assert len(transformer.references_relationships) == 1
