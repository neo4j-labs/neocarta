"""Fixtures for JDBC schema connector unit tests.

The autouse ``_mock_java_check`` fixture patches the Java availability probe so
constructing the extractor/connector never shells out to ``java`` (which is not
present in CI). Tests that exercise the real probe import
``_assert_java_available`` directly and patch ``shutil`` / ``subprocess``.
"""

import pathlib
from unittest.mock import MagicMock, patch

import pytest

from neocarta.connectors.jdbc.schema.extract import JdbcSchemaExtractor
from neocarta.connectors.jdbc.schema.transform import JdbcSchemaTransformer

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
JAVA_CHECK = "neocarta.connectors.jdbc.schema.extract._assert_java_available"
SUBPROCESS_RUN = "neocarta.connectors.jdbc.schema.extract.subprocess.run"


@pytest.fixture(autouse=True)
def _mock_java_check():
    """Patch the Java availability check for the duration of each test."""
    with patch(JAVA_CHECK):
        yield


@pytest.fixture
def golden_catalog_json():
    """Representative SchemaCrawler serialize/JSON catalog (Postgres)."""
    return (FIXTURES / "schemacrawler_postgres.json").read_text(encoding="utf-8")


def _make_extractor(**overrides):
    """Build a JdbcSchemaExtractor with dummy connection config."""
    kwargs = {
        "jdbc_url": "jdbc:postgresql://localhost:5432/neocarta_test",
        "jdbc_driver": "org.postgresql.Driver",
        "jdbc_driver_jar": "schemacrawler-jars/postgresql.jar",
        "schemacrawler_jar": "schemacrawler-jars/schemacrawler.jar",
        "source_database_name": "neocarta_test",
    }
    kwargs.update(overrides)
    return JdbcSchemaExtractor(**kwargs)


@pytest.fixture
def extractor():
    """A JdbcSchemaExtractor with dummy connection config (java check patched)."""
    return _make_extractor()


@pytest.fixture
def extractor_with_cache(extractor, golden_catalog_json):
    """Extractor whose cache is populated from the golden JSON (subprocess mocked)."""
    completed = MagicMock(returncode=0, stdout=golden_catalog_json, stderr="")
    with patch(SUBPROCESS_RUN, return_value=completed):
        extractor.extract()
    return extractor


@pytest.fixture
def transformer():
    """A fresh JdbcSchemaTransformer."""
    return JdbcSchemaTransformer()
