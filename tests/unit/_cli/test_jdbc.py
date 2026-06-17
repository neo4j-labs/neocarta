"""Unit tests for ``neocarta jdbc schema``.

The connector requires a live Neo4j (and Java + a SchemaCrawler/JDBC-driver JAR),
so these tests cover CLI plumbing only: --help shape, --dry-run
side-effect-freeness, missing-config errors, the success envelope, secret
handling, and library-error -> exit-code routing. The connector class is mocked,
so no Java or SchemaCrawler is needed. End-to-end connector behaviour is the
integration suite's job.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from neocarta._cli import cli
from neocarta._cli.errors import EXIT_CODES
from neocarta.errors import (
    AuthError,
    ConfigError,
    Neo4jConnectionError,
    RateLimitError,
)

# The four inputs the command requires before it does anything.
_REQUIRED_ENV = {
    "JDBC_URL": "jdbc:postgresql://localhost:5432/mydb",
    "JDBC_DRIVER": "org.postgresql.Driver",
    "JDBC_DRIVER_JAR": "lib/postgresql.jar",
    "SCHEMACRAWLER_JAR": "schemacrawler/lib/*",
}


def test_schema_help_documents_key_flags():
    runner = CliRunner()
    result = runner.invoke(cli, ["jdbc", "schema", "--help"])
    assert result.exit_code == 0
    for token in (
        "--jdbc-url",
        "--jdbc-driver",
        "--jdbc-driver-jar",
        "--schemacrawler-jar",
        "--db-user",
        "--source-database-name",
        "--platform",
        "--service",
        "--timeout",
        "--schema",
        "--embeddings",
        "--no-embeddings",
        "--dry-run",
    ):
        assert token in result.output, f"--help should document {token}"


@pytest.fixture
def _required_env(monkeypatch):
    """Set the four required JDBC inputs; isolate from the repo's own .env."""
    monkeypatch.setattr("neocarta._cli.config.load_dotenv", lambda *_a, **_kw: None)
    for key, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.mark.usefixtures("_required_env")
def test_schema_dry_run_emits_json_and_skips_clients():
    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "jdbc", "schema", "--dry-run"])
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)["jdbc_schema"]
    assert body["dry_run"] is True
    assert body["jdbc_url"] == _REQUIRED_ENV["JDBC_URL"]
    assert body["embeddings"] is False


@pytest.mark.usefixtures("_required_env")
def test_schema_dry_run_never_emits_password(monkeypatch):
    monkeypatch.setenv("JDBC_PASSWORD", "super-secret")
    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "jdbc", "schema", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "super-secret" not in result.output
    assert "password" not in json.loads(result.output)["jdbc_schema"]


@pytest.mark.parametrize("missing", list(_REQUIRED_ENV))
def test_schema_missing_required_input_fails_with_usage_error(monkeypatch, missing):
    # python-dotenv walks up from CWD for a .env; stub it so the repo's own
    # .env cannot supply the input we are deliberately removing.
    monkeypatch.setattr("neocarta._cli.config.load_dotenv", lambda *_a, **_kw: None)
    for key, value in _REQUIRED_ENV.items():
        if key == missing:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "jdbc", "schema", "--dry-run"])
    assert result.exit_code == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "usage_error"


@pytest.fixture
def _cli_env(monkeypatch):
    """Populate every env var required for the command to start a real run."""
    monkeypatch.setattr("neocarta._cli.config.load_dotenv", lambda *_a, **_kw: None)
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "password")
    for key, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.mark.usefixtures("_cli_env")
def test_schema_success_emits_json_and_forwards_inputs(monkeypatch):
    monkeypatch.setenv("JDBC_PASSWORD", "db-secret")
    runner = CliRunner()
    with (
        patch("neocarta._cli.commands.jdbc._neo4j_driver") as mock_driver_ctx,
        patch(
            "neocarta.connectors.jdbc.JdbcSchemaConnector", return_value=MagicMock()
        ) as mock_connector,
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False
        result = runner.invoke(
            cli, ["--json", "jdbc", "schema", "--schema", "public", "--schema", "sales"]
        )

    assert result.exit_code == 0, result.output
    out = result.output
    payload = json.loads(out[out.index("{") :])
    assert payload["jdbc_schema"]["status"] == "succeeded"

    # The secret reaches the connector but is sourced from JDBC_PASSWORD only,
    # and never surfaces in the output envelope.
    _, kwargs = mock_connector.call_args
    assert kwargs["jdbc_url"] == _REQUIRED_ENV["JDBC_URL"]
    assert kwargs["db_password"] == "db-secret"  # noqa: S105
    assert "db-secret" not in result.output
    # The repeatable --schema flag is forwarded to ingest().
    mock_connector.return_value.ingest.assert_called_once_with(schemas=["public", "sales"])


@pytest.mark.parametrize(
    ("error", "expected_exit_code"),
    [
        (ConfigError("bad config"), EXIT_CODES["validation_error"]["code"]),
        (AuthError("bad credentials"), EXIT_CODES["auth_error"]["code"]),
        (RateLimitError("quota exceeded"), EXIT_CODES["rate_limited"]["code"]),
        (Neo4jConnectionError("Cannot reach Neo4j."), EXIT_CODES["upstream_error"]["code"]),
    ],
)
@pytest.mark.usefixtures("_cli_env")
def test_schema_routes_library_errors_to_exit_codes(error, expected_exit_code):
    """Every NeocartaError raised from the connector becomes its CLI code."""
    runner = CliRunner()
    with (
        patch("neocarta._cli.commands.jdbc._neo4j_driver") as mock_driver_ctx,
        patch("neocarta.connectors.jdbc.JdbcSchemaConnector", side_effect=error),
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False
        result = runner.invoke(cli, ["jdbc", "schema"])

    assert result.exit_code == expected_exit_code, (
        f"{type(error).__name__} should exit {expected_exit_code}, got {result.exit_code}."
    )
