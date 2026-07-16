"""Unit tests for ``neocarta dataplex schema`` and ``neocarta dataplex glossary``.

The connectors require live Dataplex + Neo4j, so these tests cover the CLI
plumbing only: --help shape, --dry-run side-effect-freeness, missing-config
errors, the success envelope, and library-error → exit-code routing. End-to-end
connector behaviour is exercised by the integration suite.
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


# --------------------------------------------------------------------------- #
# --help
# --------------------------------------------------------------------------- #
def test_schema_help_documents_key_flags():
    runner = CliRunner()
    result = runner.invoke(cli, ["dataplex", "schema", "--help"])
    assert result.exit_code == 0
    for token in (
        "--project-id",
        "--project-number",
        "--dataplex-location",
        "--dataset-id",
        "--embeddings",
        "--no-embeddings",
        "--embedding-dimensions",
        "--embedding-batch-size",
        "--dry-run",
    ):
        assert token in result.output, f"--help should document {token}"


def test_glossary_help_documents_key_flags_and_omits_dataset():
    runner = CliRunner()
    result = runner.invoke(cli, ["dataplex", "glossary", "--help"])
    assert result.exit_code == 0
    for token in (
        "--project-id",
        "--project-number",
        "--dataplex-location",
        "--entry-links",
        "--no-entry-links",
        "--embeddings",
        "--no-embeddings",
        "--embedding-dimensions",
        "--embedding-batch-size",
        "--dry-run",
    ):
        assert token in result.output, f"--help should document {token}"
    # glossary is dataset-independent.
    assert "--dataset-id" not in result.output


# --------------------------------------------------------------------------- #
# --dry-run
# --------------------------------------------------------------------------- #
def test_schema_dry_run_emits_json_and_skips_clients():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--json",
            "dataplex",
            "schema",
            "--project-id",
            "fake-proj",
            "--project-number",
            "123456",
            "--dataplex-location",
            "us",
            "--dataset-id",
            "demo_ds",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)["dataplex_schema"]
    assert body["dry_run"] is True
    assert body["project_id"] == "fake-proj"
    assert body["project_number"] == "123456"
    assert body["dataplex_location"] == "us"
    assert body["dataset_id"] == "demo_ds"
    assert body["embeddings"] is False


def test_glossary_dry_run_emits_json_and_needs_no_dataset():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--json",
            "dataplex",
            "glossary",
            "--project-id",
            "fake-proj",
            "--project-number",
            "123456",
            "--dataplex-location",
            "us",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)["dataplex_glossary"]
    assert body["dry_run"] is True
    assert body["project_id"] == "fake-proj"
    assert body["entry_links"] is True
    assert body["embeddings"] is False
    assert "dataset_id" not in body


def test_schema_dry_run_reports_embedding_batch_size_when_enabled():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--json",
            "dataplex",
            "schema",
            "--project-id",
            "fake-proj",
            "--project-number",
            "123456",
            "--dataplex-location",
            "us",
            "--dataset-id",
            "demo_ds",
            "--embeddings",
            "--embedding-batch-size",
            "8",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)["dataplex_schema"]
    assert body["embeddings"] is True
    assert body["embedding_batch_size"] == 8


# --------------------------------------------------------------------------- #
# missing required config → usage error (one case per required field)
# --------------------------------------------------------------------------- #
_SCHEMA_REQUIRED = {
    "GCP_PROJECT_ID": "fake-proj",
    "GCP_PROJECT_NUMBER": "123456",
    "DATAPLEX_LOCATION": "us",
    "BIGQUERY_DATASET_ID": "demo_ds",
}
_GLOSSARY_REQUIRED = {
    "GCP_PROJECT_ID": "fake-proj",
    "GCP_PROJECT_NUMBER": "123456",
    "DATAPLEX_LOCATION": "us",
}


def _invoke_missing(monkeypatch, verb, required_env, missing_env):
    # python-dotenv walks up from CWD and finds the repo's own .env, so stub it
    # out and drive the environment explicitly.
    monkeypatch.setattr("neocarta._cli.config.load_dotenv", lambda *_a, **_kw: None)
    for key, value in required_env.items():
        if key == missing_env:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    return CliRunner().invoke(cli, ["--json", "dataplex", verb, "--dry-run"])


@pytest.mark.parametrize(
    ("missing_env", "flag_token"),
    [
        ("GCP_PROJECT_ID", "project-id"),
        ("GCP_PROJECT_NUMBER", "project-number"),
        ("DATAPLEX_LOCATION", "dataplex-location"),
        ("BIGQUERY_DATASET_ID", "dataset-id"),
    ],
)
def test_schema_missing_required_fails_with_usage_error(monkeypatch, missing_env, flag_token):
    result = _invoke_missing(monkeypatch, "schema", _SCHEMA_REQUIRED, missing_env)
    assert result.exit_code == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "usage_error"
    assert flag_token in payload["error"]["message"].lower()


@pytest.mark.parametrize(
    ("missing_env", "flag_token"),
    [
        ("GCP_PROJECT_ID", "project-id"),
        ("GCP_PROJECT_NUMBER", "project-number"),
        ("DATAPLEX_LOCATION", "dataplex-location"),
    ],
)
def test_glossary_missing_required_fails_with_usage_error(monkeypatch, missing_env, flag_token):
    result = _invoke_missing(monkeypatch, "glossary", _GLOSSARY_REQUIRED, missing_env)
    assert result.exit_code == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "usage_error"
    assert flag_token in payload["error"]["message"].lower()


# --------------------------------------------------------------------------- #
# success envelope + error routing
# --------------------------------------------------------------------------- #
@pytest.fixture
def _cli_env(monkeypatch):
    """Populate the env vars both dataplex verbs need to start."""
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "password")
    monkeypatch.setenv("GCP_PROJECT_ID", "fake-proj")
    monkeypatch.setenv("GCP_PROJECT_NUMBER", "123456")
    monkeypatch.setenv("DATAPLEX_LOCATION", "us")
    monkeypatch.setenv("BIGQUERY_DATASET_ID", "demo_ds")


@pytest.mark.parametrize("verb", ["schema", "glossary"])
@pytest.mark.usefixtures("_cli_env")
def test_success_emits_json(verb):
    runner = CliRunner()
    with (
        patch("neocarta._cli.commands.dataplex._neo4j_driver") as mock_driver_ctx,
        patch("neocarta.connectors.dataplex.DataplexSchemaConnector", return_value=MagicMock()),
        patch("neocarta.connectors.dataplex.DataplexGlossaryConnector", return_value=MagicMock()),
        patch("google.cloud.dataplex_v1.CatalogServiceClient"),
        patch("google.cloud.dataplex_v1.BusinessGlossaryServiceClient"),
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False

        result = runner.invoke(cli, ["--json", "dataplex", verb])

    assert result.exit_code == 0, result.output
    # Progress lines go to the stderr console (CliRunner mixes them into output);
    # the JSON result is the final object on stdout.
    out = result.output
    payload = json.loads(out[out.index("{") :])
    assert payload[f"dataplex_{verb}"]["status"] == "succeeded"
    assert payload[f"dataplex_{verb}"]["embeddings"] is False


@pytest.mark.parametrize(
    ("error", "expected_exit_code"),
    [
        (ConfigError("bad project"), EXIT_CODES["validation_error"]["code"]),
        (AuthError("bad credentials"), EXIT_CODES["auth_error"]["code"]),
        (RateLimitError("quota exceeded"), EXIT_CODES["rate_limited"]["code"]),
        (Neo4jConnectionError("Cannot reach Neo4j."), EXIT_CODES["upstream_error"]["code"]),
    ],
)
@pytest.mark.usefixtures("_cli_env")
def test_schema_routes_library_errors_to_exit_codes(error: NeocartaError, expected_exit_code: int):
    """Every NeocartaError raised from the Dataplex connector becomes its CLI code."""
    runner = CliRunner()
    with (
        patch("neocarta._cli.commands.dataplex._neo4j_driver") as mock_driver_ctx,
        patch("neocarta.connectors.dataplex.DataplexSchemaConnector", side_effect=error),
        patch("google.cloud.dataplex_v1.CatalogServiceClient"),
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False

        result = runner.invoke(cli, ["dataplex", "schema"])

    assert result.exit_code == expected_exit_code, (
        f"{type(error).__name__} should exit {expected_exit_code}, got {result.exit_code}. "
        f"Output: {result.output!r}"
    )
