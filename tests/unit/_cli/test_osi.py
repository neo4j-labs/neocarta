"""Unit tests for ``neocarta osi ingest``.

The connector requires a live Neo4j, so these tests cover the CLI plumbing
only: --help shape, --dry-run side-effect-freeness, missing-config errors, the
success envelope, and library-error → exit-code routing. End-to-end connector
behaviour is exercised by the integration suite.
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

_SPEC_SOURCE = "datasets/osi/acme_semantic_model.yaml"


def test_ingest_help_documents_key_flags():
    runner = CliRunner()
    result = runner.invoke(cli, ["osi", "ingest", "--help"])
    assert result.exit_code == 0
    output = result.output
    for token in ("--spec-source", "--embeddings", "--no-embeddings", "--dry-run"):
        assert token in output, f"--help should document {token}"


def test_ingest_dry_run_emits_json_and_skips_clients():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--json",
            "osi",
            "ingest",
            "--spec-source",
            _SPEC_SOURCE,
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    body = payload["osi_ingest"]
    assert body["dry_run"] is True
    assert body["spec_source"] == _SPEC_SOURCE
    assert body["embeddings"] is False


def test_ingest_missing_spec_source_fails_with_usage_error(monkeypatch):
    # python-dotenv walks up from CWD looking for .env, so even from an isolated
    # tmp dir it finds the repo's own .env. Stub it out and clear the env var we
    # want absent for this test.
    monkeypatch.setattr("neocarta._cli.config.load_dotenv", lambda *_a, **_kw: None)
    monkeypatch.delenv("OSI_SPEC_SOURCE", raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "osi", "ingest", "--dry-run"])
    # CLIError("usage_error") → exit code 2 per the AGENTS-CLI map.
    assert result.exit_code == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "usage_error"
    assert "spec-source" in payload["error"]["message"].lower()


@pytest.fixture
def _cli_env(monkeypatch):
    """Populate the env vars required for the osi command to start."""
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "password")
    monkeypatch.setenv("OSI_SPEC_SOURCE", _SPEC_SOURCE)


@pytest.mark.usefixtures("_cli_env")
def test_ingest_success_emits_json():
    runner = CliRunner()
    with (
        patch("neocarta._cli.commands.osi._neo4j_driver") as mock_driver_ctx,
        patch("neocarta.connectors.osi.OsiConnector", return_value=MagicMock()),
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False

        result = runner.invoke(cli, ["--json", "osi", "ingest"])

    assert result.exit_code == 0, result.output
    # Progress lines are written to the stderr console (CliRunner mixes them
    # into output); the JSON result is the final object on stdout.
    out = result.output
    payload = json.loads(out[out.index("{") :])
    assert payload["osi_ingest"]["status"] == "succeeded"
    assert payload["osi_ingest"]["embeddings"] is False


@pytest.mark.parametrize(
    ("error", "expected_exit_code"),
    [
        (ConfigError("spec_source does not exist"), EXIT_CODES["validation_error"]["code"]),
        (AuthError("bad credentials"), EXIT_CODES["auth_error"]["code"]),
        (RateLimitError("quota exceeded"), EXIT_CODES["rate_limited"]["code"]),
        (Neo4jConnectionError("Cannot reach Neo4j."), EXIT_CODES["upstream_error"]["code"]),
    ],
)
@pytest.mark.usefixtures("_cli_env")
def test_osi_ingest_routes_library_errors_to_exit_codes(
    error: NeocartaError, expected_exit_code: int
):
    """Every NeocartaError raised from the OSI connector becomes its CLI code."""
    runner = CliRunner()
    with (
        patch("neocarta._cli.commands.osi._neo4j_driver") as mock_driver_ctx,
        patch("neocarta.connectors.osi.OsiConnector", side_effect=error),
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False

        result = runner.invoke(cli, ["osi", "ingest"])

    assert result.exit_code == expected_exit_code, (
        f"{type(error).__name__} should exit {expected_exit_code}, got {result.exit_code}. "
        f"Output: {result.output!r}"
    )
