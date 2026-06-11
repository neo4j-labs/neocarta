"""Unit tests for the JDBC schema extractor (SchemaCrawler subprocess bridge)."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from neocarta.connectors.jdbc.schema.extract import (
    JdbcSchemaExtractor,
    _assert_java_available,
    _parse_java_major,
    derive_source_database_name,
)
from neocarta.errors import ConfigError, ExtractionError, OperationTimeoutError

WHICH = "neocarta.connectors.jdbc.schema.extract.shutil.which"
SUBPROCESS_RUN = "neocarta.connectors.jdbc.schema.extract.subprocess.run"


# --------------------------------------------------------------------------- #
# URL parsing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("jdbc:postgresql://localhost:5432/mydb", "mydb"),
        ("jdbc:postgresql://localhost:5432/mydb?ssl=true", "mydb"),
        ("jdbc:mysql://host:3306/analytics", "analytics"),
        ("jdbc:oracle:thin:@host:1521:ORCL", None),
        ("jdbc:sqlserver://host;databaseName=mydb", None),
    ],
)
def test_derive_source_database_name(url, expected):
    """The DB name is parsed from path-based URLs and None otherwise."""
    assert derive_source_database_name(url) == expected


# --------------------------------------------------------------------------- #
# Command construction (filtered vs unfiltered + password handling)
# --------------------------------------------------------------------------- #
def test_build_command_unfiltered_has_no_schemas_flag(extractor):
    """Uses the FreeMarker template command, and without `schemas` emits no --schemas flag."""
    cmd = extractor.build_command()
    assert "--command=template" in cmd
    assert "--templating-language=freemarker" in cmd
    assert "--info-level=detailed" in cmd
    assert any(arg.startswith("--template=") and arg.endswith("catalog.json.ftl") for arg in cmd)
    assert not any(arg.startswith("--schemas=") for arg in cmd)


def test_build_command_filtered_joins_schemas_as_regex(extractor):
    """With `schemas`, names are joined into a regex alternation."""
    cmd = extractor.build_command(["public", "analytics"])
    assert "--schemas=public|analytics" in cmd


def test_build_command_password_passed_via_env_not_argv():
    """The DB password is referenced via --password:env and never appears in argv."""
    secret = "super-secret-pw"  # noqa: S105
    ext = JdbcSchemaExtractor(
        jdbc_url="jdbc:postgresql://localhost:5432/neocarta_test",
        jdbc_driver="org.postgresql.Driver",
        jdbc_driver_jar="schemacrawler-jars/postgresql.jar",
        schemacrawler_jar="schemacrawler-jars/schemacrawler.jar",
        source_database_name="neocarta_test",
        db_user="postgres",
        db_password=secret,
    )
    cmd = ext.build_command()
    assert "--user=postgres" in cmd
    assert "--password:env=NEOCARTA_JDBC_PASSWORD" in cmd
    assert all(secret not in arg for arg in cmd)


# --------------------------------------------------------------------------- #
# Cache flattening from the golden catalog
# --------------------------------------------------------------------------- #
def test_extract_populates_database_and_schema_info(extractor_with_cache):
    """database_info has one row; schema_info has both schemas."""
    db = extractor_with_cache.database_info
    assert list(db["database_name"]) == ["neocarta_test"]

    schemas = extractor_with_cache.schema_info
    assert sorted(schemas["schema_name"]) == ["analytics", "public"]


def test_extract_populates_table_info(extractor_with_cache):
    """All base tables across schemas are flattened."""
    tables = extractor_with_cache.table_info
    assert sorted(tables["table_name"]) == ["customers", "daily_revenue", "orders"]


def test_extract_populates_column_info_with_flags(extractor_with_cache):
    """Columns carry type, nullable, and pk/fk flags."""
    cols = extractor_with_cache.column_info
    assert len(cols) == 7

    cust_id = cols[(cols["table_name"] == "customers") & (cols["column_name"] == "id")].iloc[0]
    assert cust_id["type"] == "int4"
    assert cust_id["is_primary_key"]
    assert not cust_id["is_foreign_key"]
    assert not cust_id["nullable"]

    email = cols[(cols["table_name"] == "customers") & (cols["column_name"] == "email")].iloc[0]
    assert email["nullable"]
    assert not email["is_primary_key"]

    fk = cols[(cols["table_name"] == "orders") & (cols["column_name"] == "customer_id")].iloc[0]
    assert fk["is_foreign_key"]
    assert not fk["is_primary_key"]


def test_extract_populates_column_references(extractor_with_cache):
    """Foreign keys are flattened into source/target reference rows."""
    refs = extractor_with_cache.column_references_info
    assert len(refs) == 1
    row = refs.iloc[0]
    assert row["source_table_name"] == "orders"
    assert row["source_column_name"] == "customer_id"
    assert row["target_table_name"] == "customers"
    assert row["target_column_name"] == "id"


# --------------------------------------------------------------------------- #
# Java availability probe
# --------------------------------------------------------------------------- #
def test_assert_java_available_raises_when_java_missing():
    """ConfigError is raised when java is not on PATH."""
    with patch(WHICH, return_value=None), pytest.raises(ConfigError, match="Java runtime"):
        _assert_java_available()


def test_assert_java_available_raises_when_version_fails():
    """ConfigError is raised when `java -version` exits non-zero."""
    failed = MagicMock(returncode=1, stderr="no runtime")
    with (
        patch(WHICH, return_value="/usr/bin/java"),
        patch(SUBPROCESS_RUN, return_value=failed),
        pytest.raises(ConfigError, match="non-zero"),
    ):
        _assert_java_available()


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ('openjdk version "17.0.19" 2026-04-21', 17),
        ('openjdk version "11.0.2" 2019-01-15', 11),
        ('java version "1.8.0_392"', 8),
        ('openjdk version "21" 2023-09-19', 21),
        ("no version string here", None),
    ],
)
def test_parse_java_major(output, expected):
    """Major version is parsed from modern and legacy `java -version` strings."""
    assert _parse_java_major(output) == expected


def test_assert_java_available_rejects_below_11():
    """A Java runtime older than 11 raises ConfigError."""
    java8 = MagicMock(returncode=0, stderr='openjdk version "1.8.0_392"', stdout="")
    with (
        patch(WHICH, return_value="/usr/bin/java"),
        patch(SUBPROCESS_RUN, return_value=java8),
        pytest.raises(ConfigError, match="requires Java 11"),
    ):
        _assert_java_available()


def test_assert_java_available_accepts_11_plus():
    """A Java 11+ runtime passes the probe."""
    java17 = MagicMock(returncode=0, stderr='openjdk version "17.0.19" 2026-04-21', stdout="")
    with (
        patch(WHICH, return_value="/usr/bin/java"),
        patch(SUBPROCESS_RUN, return_value=java17),
    ):
        _assert_java_available()  # no raise


def test_extract_populates_database_service(extractor_with_cache):
    """service is derived from the SchemaCrawler product name; platform is unset."""
    db = extractor_with_cache.database_info
    assert list(db["database_name"]) == ["neocarta_test"]
    assert list(db["service"]) == ["PostgreSQL"]
    assert db["platform"].isna().all()


# --------------------------------------------------------------------------- #
# Subprocess failure mapping
# --------------------------------------------------------------------------- #
def test_extract_raises_extraction_error_on_nonzero_exit(extractor):
    """A non-zero SchemaCrawler exit becomes ExtractionError."""
    failed = MagicMock(returncode=1, stdout="", stderr="boom")
    with (
        patch(SUBPROCESS_RUN, return_value=failed),
        pytest.raises(ExtractionError, match="exited with code 1"),
    ):
        extractor.extract()


def test_extract_raises_extraction_error_on_bad_json(extractor):
    """Invalid JSON output becomes ExtractionError."""
    bad = MagicMock(returncode=0, stdout="not json", stderr="")
    with (
        patch(SUBPROCESS_RUN, return_value=bad),
        pytest.raises(ExtractionError, match="valid JSON"),
    ):
        extractor.extract()


def test_extract_raises_timeout_error(extractor):
    """A subprocess timeout becomes OperationTimeoutError."""
    with (
        patch(SUBPROCESS_RUN, side_effect=subprocess.TimeoutExpired(cmd="java", timeout=1)),
        pytest.raises(OperationTimeoutError),
    ):
        extractor.extract()
