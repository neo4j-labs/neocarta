"""Unit tests for ``neocarta query-log ingest``.

The connector requires a live Neo4j, so these tests cover the CLI plumbing
only: --help shape, --dry-run side-effect-freeness, missing-config and
missing-file errors, the success envelope, and library-error → exit-code
routing. End-to-end connector behaviour is exercised by the integration suite.
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
    NeocartaError,
    RateLimitError,
)


def test_ingest_help_documents_key_flags():
    runner = CliRunner()
    result = runner.invoke(cli, ["query-log", "ingest", "--help"])
    assert result.exit_code == 0
    output = result.output
    for token in ("--query-log-file", "--source", "--dry-run"):
        assert token in output, f"--help should document {token}"


def test_ingest_dry_run_emits_json_and_skips_clients():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--json",
            "query-log",
            "ingest",
            "--query-log-file",
            "logs.json",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    body = payload["query_log_ingest"]
    assert body["dry_run"] is True
    assert body["query_log_file"] == "logs.json"
    assert body["source"] == "bigquery"


def test_ingest_missing_file_flag_fails_with_usage_error(monkeypatch):
    # python-dotenv walks up from CWD looking for .env, so even from an isolated
    # tmp dir it finds the repo's own .env. Stub it out and clear the env var we
    # want absent for this test.
    monkeypatch.setattr("neocarta._cli.config.load_dotenv", lambda *_a, **_kw: None)
    monkeypatch.delenv("QUERY_LOG_FILE", raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "query-log", "ingest", "--dry-run"])
    # CLIError("usage_error") → exit code 2 per the AGENTS-CLI map.
    assert result.exit_code == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "usage_error"
    assert "query-log-file" in payload["error"]["message"].lower()


@pytest.fixture
def _cli_env(monkeypatch):
    """Populate the env vars required for the query-log command to start."""
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "password")


@pytest.mark.usefixtures("_cli_env")
def test_ingest_nonexistent_file_fails_with_not_found(monkeypatch):
    """A missing file is mapped to the not_found exit code before any DB work."""
    monkeypatch.setenv("QUERY_LOG_FILE", "/no/such/query_log.json")
    runner = CliRunner()
    with patch("neocarta._cli.commands.query_log._neo4j_driver") as mock_driver_ctx:
        result = runner.invoke(cli, ["--json", "query-log", "ingest"])

    assert result.exit_code == EXIT_CODES["not_found"]["code"], result.output
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "not_found"
    # The pre-flight check must short-circuit before a driver is ever built.
    mock_driver_ctx.assert_not_called()


@pytest.mark.usefixtures("_cli_env")
def test_ingest_success_emits_json(tmp_path, monkeypatch):
    log_file = tmp_path / "query_log.json"
    log_file.write_text("[]")
    monkeypatch.setenv("QUERY_LOG_FILE", str(log_file))

    mock_connector = MagicMock()
    mock_connector.extractor.query_info = [{"q": 1}, {"q": 2}]
    mock_connector.extractor.table_info = [{"t": 1}]
    mock_connector.extractor.column_info = [{"c": 1}, {"c": 2}, {"c": 3}]

    runner = CliRunner()
    with (
        patch("neocarta._cli.commands.query_log._neo4j_driver") as mock_driver_ctx,
        patch(
            "neocarta.connectors.query_log.QueryLogConnector",
            return_value=mock_connector,
        ),
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False

        result = runner.invoke(cli, ["--json", "query-log", "ingest"])

    assert result.exit_code == 0, result.output
    # Progress lines are written to the stderr console (CliRunner mixes them
    # into output); the JSON result is the final object on stdout.
    out = result.output
    payload = json.loads(out[out.index("{") :])
    body = payload["query_log_ingest"]
    assert body["status"] == "succeeded"
    assert body["source"] == "bigquery"
    assert body["queries"] == 2
    assert body["tables_referenced"] == 1
    assert body["columns_referenced"] == 3
    # Use the standardized .ingest() entrypoint, not the deprecated .run() shim.
    mock_connector.ingest.assert_called_once_with(query_log_file=str(log_file), source="bigquery")
    mock_connector.run.assert_not_called()


@pytest.mark.parametrize(
    ("error", "expected_exit_code"),
    [
        (ConfigError("Unsupported source: snowflake"), EXIT_CODES["validation_error"]["code"]),
        (AuthError("bad credentials"), EXIT_CODES["auth_error"]["code"]),
        (RateLimitError("quota exceeded"), EXIT_CODES["rate_limited"]["code"]),
        (Neo4jConnectionError("Cannot reach Neo4j."), EXIT_CODES["upstream_error"]["code"]),
    ],
)
@pytest.mark.usefixtures("_cli_env")
def test_query_log_ingest_routes_library_errors_to_exit_codes(
    error: NeocartaError, expected_exit_code: int, tmp_path, monkeypatch
):
    """Every NeocartaError raised from the query-log connector becomes its CLI code."""
    log_file = tmp_path / "query_log.json"
    log_file.write_text("[]")
    monkeypatch.setenv("QUERY_LOG_FILE", str(log_file))

    runner = CliRunner()
    with (
        patch("neocarta._cli.commands.query_log._neo4j_driver") as mock_driver_ctx,
        patch("neocarta.connectors.query_log.QueryLogConnector", side_effect=error),
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False

        result = runner.invoke(cli, ["query-log", "ingest"])

    assert result.exit_code == expected_exit_code, (
        f"{type(error).__name__} should exit {expected_exit_code}, got {result.exit_code}. "
        f"Output: {result.output!r}"
    )
