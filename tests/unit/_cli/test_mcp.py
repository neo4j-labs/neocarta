"""Unit tests for ``neocarta mcp serve``.

Starting the server needs the optional ``mcp`` extra and a live Neo4j, so these
tests cover the CLI plumbing only: --help shape, --dry-run side-effect-freeness,
the missing-extra and missing-config error paths, and that the success path
delegates to the existing :func:`neocarta._mcp.server.run` entry point. The
server's own behaviour is exercised by the MCP integration suite.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from neocarta._cli import cli
from neocarta._cli.errors import EXIT_CODES

# Where the lazily-imported server entry point lives; patched so no real server
# is started by the success test.
_SERVER_RUN = "neocarta._mcp.server.run"
# The command's module-local extra check; patched to decouple tests from whether
# fastmcp/mcp happen to be installed in the test environment.
_EXTRA_CHECK = "neocarta._cli.commands.mcp._mcp_extra_installed"


@pytest.fixture
def _cli_env(monkeypatch):
    """Populate the Neo4j env vars the serve command validates before starting."""
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "password")


def test_mcp_group_help_lists_serve():
    runner = CliRunner()
    result = runner.invoke(cli, ["mcp", "--help"])
    assert result.exit_code == 0
    assert "serve" in result.output


def test_serve_help_documents_flags_and_extra():
    runner = CliRunner()
    result = runner.invoke(cli, ["mcp", "serve", "--help"])
    assert result.exit_code == 0
    output = result.output
    for token in ("--dry-run", "--json", "mcp"):
        assert token in output, f"--help should document {token}"


def test_serve_dry_run_emits_json_and_does_not_start_server():
    runner = CliRunner()
    with patch(_SERVER_RUN) as mock_run:
        result = runner.invoke(cli, ["--json", "mcp", "serve", "--dry-run"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    body = payload["mcp_serve"]
    assert body["dry_run"] is True
    assert body["transport"] == "stdio"
    assert "database" in body
    assert "mcp_extra_installed" in body
    # Dry-run must never start the server.
    mock_run.assert_not_called()


def test_serve_missing_extra_fails_with_usage_error():
    runner = CliRunner()
    with (
        patch(_EXTRA_CHECK, return_value=False),
        patch(_SERVER_RUN) as mock_run,
    ):
        result = runner.invoke(cli, ["--json", "mcp", "serve"])

    assert result.exit_code == EXIT_CODES["usage_error"]["code"], result.output
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "usage_error"
    assert "neocarta[mcp]" in payload["error"]["suggestion"]
    # We must fail before ever importing/starting the server.
    mock_run.assert_not_called()


def test_serve_missing_neo4j_config_fails_with_usage_error(monkeypatch):
    # python-dotenv walks up from CWD and would find the repo's own .env; stub it
    # and clear the Neo4j vars so this test sees them as truly absent.
    monkeypatch.setattr("neocarta._cli.config.load_dotenv", lambda *_a, **_kw: None)
    for var in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"):
        monkeypatch.delenv(var, raising=False)

    runner = CliRunner()
    with (
        patch(_EXTRA_CHECK, return_value=True),
        patch(_SERVER_RUN) as mock_run,
    ):
        result = runner.invoke(cli, ["--json", "mcp", "serve"])

    assert result.exit_code == EXIT_CODES["usage_error"]["code"], result.output
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "usage_error"
    assert "NEO4J" in payload["error"]["message"]
    # Config is validated before the server is imported/started.
    mock_run.assert_not_called()


@pytest.mark.usefixtures("_cli_env")
def test_serve_success_delegates_to_server_run():
    runner = CliRunner()
    mock_run = MagicMock()
    with (
        patch(_EXTRA_CHECK, return_value=True),
        patch(_SERVER_RUN, mock_run),
    ):
        result = runner.invoke(cli, ["mcp", "serve"])

    assert result.exit_code == 0, result.output
    mock_run.assert_called_once_with()
