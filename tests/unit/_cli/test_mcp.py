"""Unit tests for ``neocarta mcp serve``.

These run in the plain ``[cli]`` test environment, which does **not** install the
optional ``mcp`` extra (no ``fastmcp``). They therefore must not import
:mod:`neocarta._mcp.server` (which imports ``fastmcp`` and instantiates a
required-field ``Settings()`` at module load). A stand-in server module is
injected into ``sys.modules`` so the command's lazy
``from ..._mcp.server import run`` resolves to a mock — letting us assert the
success path delegates to it, and the other paths never reach it, without the
extra installed. The real server is exercised by the MCP integration suite.
"""

import json
import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from neocarta._cli import cli
from neocarta._cli.errors import EXIT_CODES

# The command's module-local extra check; patched to decouple tests from whether
# fastmcp/mcp happen to be installed in the test environment.
_EXTRA_CHECK = "neocarta._cli.commands.mcp._mcp_extra_installed"


@pytest.fixture
def fake_server_run(monkeypatch):
    """Inject a stand-in ``neocarta._mcp.server`` module exposing a mock ``run``.

    Lets the success path exercise the real lazy ``from ..._mcp.server import
    run`` without the ``mcp`` extra (``fastmcp``) installed, and lets the other
    paths assert the server was never started.
    """
    module = types.ModuleType("neocarta._mcp.server")
    run = MagicMock(name="run")
    module.run = run
    monkeypatch.setitem(sys.modules, "neocarta._mcp.server", module)
    return run


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


def test_serve_dry_run_emits_json_and_does_not_start_server(fake_server_run):
    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "mcp", "serve", "--dry-run"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    body = payload["mcp_serve"]
    assert body["dry_run"] is True
    assert body["transport"] == "stdio"
    assert "database" in body
    assert "mcp_extra_installed" in body
    # Dry-run must never start the server.
    fake_server_run.assert_not_called()


def test_serve_missing_extra_fails_with_usage_error(fake_server_run):
    runner = CliRunner()
    with patch(_EXTRA_CHECK, return_value=False):
        result = runner.invoke(cli, ["--json", "mcp", "serve"])

    assert result.exit_code == EXIT_CODES["usage_error"]["code"], result.output
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "usage_error"
    assert "neocarta[mcp]" in payload["error"]["suggestion"]
    # We must fail before ever importing/starting the server.
    fake_server_run.assert_not_called()


def test_serve_missing_neo4j_config_fails_with_usage_error(monkeypatch, fake_server_run):
    # python-dotenv walks up from CWD and would find the repo's own .env; stub it
    # and clear the Neo4j vars so this test sees them as truly absent.
    monkeypatch.setattr("neocarta._cli.config.load_dotenv", lambda *_a, **_kw: None)
    for var in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"):
        monkeypatch.delenv(var, raising=False)

    runner = CliRunner()
    with patch(_EXTRA_CHECK, return_value=True):
        result = runner.invoke(cli, ["--json", "mcp", "serve"])

    assert result.exit_code == EXIT_CODES["usage_error"]["code"], result.output
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "usage_error"
    assert "NEO4J" in payload["error"]["message"]
    # Config is validated before the server is imported/started.
    fake_server_run.assert_not_called()


@pytest.mark.usefixtures("_cli_env")
def test_serve_success_delegates_to_server_run(fake_server_run):
    runner = CliRunner()
    with patch(_EXTRA_CHECK, return_value=True):
        result = runner.invoke(cli, ["mcp", "serve"])

    assert result.exit_code == 0, result.output
    fake_server_run.assert_called_once_with()
