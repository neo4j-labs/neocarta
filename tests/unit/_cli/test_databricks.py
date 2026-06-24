"""Unit tests for ``neocarta databricks tags``.

The connector needs a live Databricks workspace + Neo4j, so these tests cover CLI
plumbing only: --help shape, group/agent-context registration, --dry-run
side-effect-freeness, missing-config errors, the success envelope, secret
handling, and library-error -> exit-code routing. The connector and the
Databricks SDK client are mocked, so nothing reaches a real workspace.
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

_HOST = "https://dbc-test.cloud.databricks.com"


def test_group_and_help_document_tags_verb():
    runner = CliRunner()
    group = runner.invoke(cli, ["databricks", "--help"])
    assert group.exit_code == 0
    assert "tags" in group.output

    result = runner.invoke(cli, ["databricks", "tags", "--help"])
    assert result.exit_code == 0
    for token in (
        "--host",
        "--include-system-tags",
        "--system-prefixes",
        "--source",
        "--embeddings",
        "--no-embeddings",
        "--dry-run",
    ):
        assert token in result.output, f"--help should document {token}"


def test_agent_context_registers_databricks_tags():
    runner = CliRunner()
    payload = json.loads(runner.invoke(cli, ["agent-context"]).output)
    assert "databricks" in payload["commands"]
    assert "tags" in payload["commands"]["databricks"]["subcommands"]
    assert "DATABRICKS_HOST" in payload["env_vars"]
    assert "DATABRICKS_TOKEN" in payload["env_vars"]


@pytest.fixture
def _host_env(monkeypatch):
    """Set DATABRICKS_HOST and isolate from the repo's own .env."""
    monkeypatch.setattr("neocarta._cli.config.load_dotenv", lambda *_a, **_kw: None)
    monkeypatch.setenv("DATABRICKS_HOST", _HOST)


@pytest.mark.usefixtures("_host_env")
def test_dry_run_emits_json_without_token_or_clients(monkeypatch):
    # Dry-run needs only --host; it must work even with no token set.
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "databricks", "tags", "--dry-run"])
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)["databricks_tags"]
    assert body["dry_run"] is True
    assert body["host"] == _HOST
    assert body["embeddings"] is False
    # The default platform-prefix exclusion set is surfaced in the plan.
    assert body["system_prefixes"] == ["system.", "class.", "ai.", "sap."]


@pytest.mark.usefixtures("_host_env")
def test_dry_run_reflects_custom_system_prefixes(monkeypatch):
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["--json", "databricks", "tags", "--dry-run", "--system-prefixes", "system.,foo."]
    )
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)["databricks_tags"]
    assert body["system_prefixes"] == ["system.", "foo."]


@pytest.mark.usefixtures("_host_env")
def test_dry_run_never_emits_token(monkeypatch):
    monkeypatch.setenv("DATABRICKS_TOKEN", "super-secret")
    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "databricks", "tags", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "super-secret" not in result.output


def test_missing_host_fails_with_usage_error(monkeypatch):
    monkeypatch.setattr("neocarta._cli.config.load_dotenv", lambda *_a, **_kw: None)
    monkeypatch.delenv("DATABRICKS_HOST", raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "databricks", "tags", "--dry-run"])
    assert result.exit_code == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "usage_error"


@pytest.fixture
def _cli_env(monkeypatch):
    """Populate every env var required for the command to start a real run."""
    monkeypatch.setattr("neocarta._cli.config.load_dotenv", lambda *_a, **_kw: None)
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "password")
    monkeypatch.setenv("DATABRICKS_HOST", _HOST)


@pytest.mark.usefixtures("_cli_env")
def test_success_forwards_token_to_client_and_hides_it(monkeypatch):
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-secret")
    runner = CliRunner()
    with (
        patch("neocarta._cli.commands.databricks._neo4j_driver") as mock_driver_ctx,
        patch("databricks.sdk.WorkspaceClient", return_value=MagicMock()) as mock_wsc,
        patch(
            "neocarta.connectors.databricks.DatabricksTagsConnector",
            return_value=MagicMock(),
        ) as mock_connector,
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False
        result = runner.invoke(cli, ["--json", "databricks", "tags"])

    assert result.exit_code == 0, result.output
    out = result.output
    payload = json.loads(out[out.index("{") :])
    assert payload["databricks_tags"]["status"] == "succeeded"

    # Token is read only from DATABRICKS_TOKEN, unwrapped into the SDK client,
    # and never surfaces in the output envelope.
    _, wsc_kwargs = mock_wsc.call_args
    assert wsc_kwargs["host"] == _HOST
    assert wsc_kwargs["token"] == "dapi-secret"  # noqa: S105
    assert "dapi-secret" not in result.output
    mock_connector.return_value.ingest.assert_called_once_with(include_system_tags=False)
    # The default platform-prefix set is passed to the connector.
    assert mock_connector.call_args.kwargs["system_prefixes"] == (
        "system.",
        "class.",
        "ai.",
        "sap.",
    )


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
def test_routes_library_errors_to_exit_codes(monkeypatch, error, expected_exit_code):
    """Every NeocartaError raised from the connector becomes its CLI code."""
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-secret")
    runner = CliRunner()
    with (
        patch("neocarta._cli.commands.databricks._neo4j_driver") as mock_driver_ctx,
        patch("databricks.sdk.WorkspaceClient", return_value=MagicMock()),
        patch("neocarta.connectors.databricks.DatabricksTagsConnector", side_effect=error),
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False
        result = runner.invoke(cli, ["databricks", "tags"])

    assert result.exit_code == expected_exit_code, (
        f"{type(error).__name__} should exit {expected_exit_code}, got {result.exit_code}."
    )
