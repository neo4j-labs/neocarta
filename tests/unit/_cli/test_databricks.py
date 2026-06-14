"""Unit tests for ``neocarta databricks embed``.

The embed command runs the in-process enrichment embedder against a graph the
Databricks Spark ingest job already produced, so these tests cover the CLI
plumbing only: --help shape, --dry-run side-effect-freeness, missing-config
errors, the success envelope, and library-error -> exit-code routing. The Spark
schema ingest itself is not a CLI verb (it runs as a cluster wheel job).
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


def test_embed_help_documents_key_flags():
    runner = CliRunner()
    result = runner.invoke(cli, ["databricks", "embed", "--help"])
    assert result.exit_code == 0
    output = result.output
    for token in ("--embedding-model", "--embedding-dimensions", "--dry-run"):
        assert token in output, f"--help should document {token}"
    # The embeddings toggle was intentionally dropped: embedding is the verb's
    # sole job, so there is no --embeddings/--no-embeddings flag.
    assert "--no-embeddings" not in output


def test_embed_dry_run_emits_json_and_skips_clients():
    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "databricks", "embed", "--dry-run"])
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)["databricks_embed"]
    assert body["dry_run"] is True
    assert body["embedding_model"] == "text-embedding-3-small"
    assert body["embedding_dimensions"] == 768
    assert body["node_labels"] == ["Database", "Schema", "Table", "Column"]


def test_embed_dry_run_honours_model_overrides():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--json",
            "databricks",
            "embed",
            "--dry-run",
            "--embedding-model",
            "text-embedding-3-large",
            "--embedding-dimensions",
            "1536",
        ],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)["databricks_embed"]
    assert body["embedding_model"] == "text-embedding-3-large"
    assert body["embedding_dimensions"] == 1536


def test_embed_missing_neo4j_fails_with_usage_error(monkeypatch):
    # python-dotenv walks up from CWD looking for .env, so even from an isolated
    # tmp dir it finds the repo's own .env. Stub it out and clear the Neo4j vars
    # we want absent for this test.
    monkeypatch.setattr("neocarta._cli.config.load_dotenv", lambda *_a, **_kw: None)
    for var in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "databricks", "embed"])
    # CLIError("usage_error") -> exit code 2 per the AGENTS-CLI map.
    assert result.exit_code == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "usage_error"
    assert "neo4j" in payload["error"]["message"].lower()


@pytest.fixture
def _cli_env(monkeypatch):
    """Populate the Neo4j env vars required for the embed command to start."""
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "password")


@pytest.mark.usefixtures("_cli_env")
def test_embed_success_emits_json():
    runner = CliRunner()
    with (
        patch("neocarta._cli.commands.databricks._neo4j_driver") as mock_driver_ctx,
        patch("neocarta._cli.commands.databricks._build_embedder") as mock_build,
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False

        result = runner.invoke(cli, ["--json", "databricks", "embed"])

    assert result.exit_code == 0, result.output
    mock_build.return_value.run.assert_called_once()
    # Progress lines go to the stderr console (CliRunner mixes them into output);
    # the JSON result is the final object on stdout.
    out = result.output
    payload = json.loads(out[out.index("{") :])
    assert payload["databricks_embed"]["status"] == "succeeded"
    assert payload["databricks_embed"]["node_labels"] == ["Database", "Schema", "Table", "Column"]


@pytest.mark.parametrize(
    ("error", "expected_exit_code"),
    [
        (ConfigError("bad dimension"), EXIT_CODES["validation_error"]["code"]),
        (AuthError("bad credentials"), EXIT_CODES["auth_error"]["code"]),
        (RateLimitError("quota exceeded"), EXIT_CODES["rate_limited"]["code"]),
        (Neo4jConnectionError("Cannot reach Neo4j."), EXIT_CODES["upstream_error"]["code"]),
    ],
)
@pytest.mark.usefixtures("_cli_env")
def test_embed_routes_library_errors_to_exit_codes(error: NeocartaError, expected_exit_code: int):
    """Every NeocartaError raised from the embedder becomes its CLI code."""
    runner = CliRunner()
    with (
        patch("neocarta._cli.commands.databricks._neo4j_driver") as mock_driver_ctx,
        patch("neocarta._cli.commands.databricks._build_embedder", side_effect=error),
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False

        result = runner.invoke(cli, ["databricks", "embed"])

    assert result.exit_code == expected_exit_code, (
        f"{type(error).__name__} should exit {expected_exit_code}, got {result.exit_code}. "
        f"Output: {result.output!r}"
    )
