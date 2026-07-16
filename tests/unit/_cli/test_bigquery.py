"""Unit tests for ``neocarta bigquery schema`` / ``logs``.

The connectors require live Neo4j and BigQuery clients, so these tests cover
the CLI plumbing only: --help shape, --dry-run side-effect-freeness, and
missing-config errors. End-to-end connector behaviour is exercised by the
integration suite.
"""

import json

from click.testing import CliRunner

from neocarta._cli import cli


def test_schema_help_documents_key_flags():
    runner = CliRunner()
    result = runner.invoke(cli, ["bigquery", "schema", "--help"])
    assert result.exit_code == 0
    output = result.output
    for token in (
        "--project-id",
        "--dataset-id",
        "--no-embeddings",
        "--embedding-dimensions",
        "--embedding-batch-size",
        "--dry-run",
    ):
        assert token in output, f"--help should document {token}"


def test_logs_help_documents_key_flags():
    runner = CliRunner()
    result = runner.invoke(cli, ["bigquery", "logs", "--help"])
    assert result.exit_code == 0
    output = result.output
    for token in (
        "--project-id",
        "--dataset-id",
        "--start-date",
        "--end-date",
        "--limit",
        "--include-failed-queries",
        "--embedding-model",
        "--embedding-dimensions",
        "--embedding-batch-size",
    ):
        assert token in output, f"--help should document {token}"


def test_schema_dry_run_emits_json_and_skips_clients():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--json",
            "bigquery",
            "schema",
            "--project-id",
            "fake-proj",
            "--dataset-id",
            "fake_ds",
            "--no-embeddings",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    body = payload["bigquery_schema"]
    assert body["dry_run"] is True
    assert body["project_id"] == "fake-proj"
    assert body["dataset_id"] == "fake_ds"
    assert body["embeddings"] is False


def test_schema_embeddings_off_by_default():
    # Embeddings are opt-in: with no --embeddings/--no-embeddings flag the
    # schema command must default to off, consistent with every other command.
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--json",
            "bigquery",
            "schema",
            "--project-id",
            "fake-proj",
            "--dataset-id",
            "fake_ds",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["bigquery_schema"]["embeddings"] is False


def test_schema_embeddings_opt_in():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--json",
            "bigquery",
            "schema",
            "--project-id",
            "fake-proj",
            "--dataset-id",
            "fake_ds",
            "--embeddings",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["bigquery_schema"]["embeddings"] is True


def test_logs_dry_run_emits_json_and_skips_clients():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--json",
            "bigquery",
            "logs",
            "--project-id",
            "fake-proj",
            "--dataset-id",
            "fake_ds",
            "--limit",
            "42",
            "--include-failed-queries",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    body = payload["bigquery_logs"]
    assert body["dry_run"] is True
    assert body["limit"] == 42
    assert body["drop_failed_queries"] is False


def test_schema_dry_run_reports_embedding_batch_size_and_dimensions():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--json",
            "bigquery",
            "schema",
            "--project-id",
            "fake-proj",
            "--dataset-id",
            "fake_ds",
            "--embeddings",
            "--embedding-dimensions",
            "256",
            "--embedding-batch-size",
            "8",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)["bigquery_schema"]
    assert body["embeddings"] is True
    assert body["embedding_dimensions"] == 256
    assert body["embedding_batch_size"] == 8


def test_logs_dry_run_reports_embedding_fields_when_enabled():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--json",
            "bigquery",
            "logs",
            "--project-id",
            "fake-proj",
            "--dataset-id",
            "fake_ds",
            "--embeddings",
            "--embedding-model",
            "gemini-embedding-001",
            "--embedding-batch-size",
            "16",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)["bigquery_logs"]
    assert body["embeddings"] is True
    assert body["embedding_model"] == "gemini-embedding-001"
    assert body["embedding_batch_size"] == 16


def test_schema_missing_project_id_fails_with_usage_error(monkeypatch):
    # Click 8.2+ separates result.stdout / result.stderr by default; the
    # CLIError envelope goes to stdout, the one-line summary to stderr.
    runner = CliRunner()
    # python-dotenv walks up from CWD looking for .env, so even from an
    # isolated tmp dir it finds the repo's own .env. Stub it out and clear
    # the env vars we want absent for this test.
    monkeypatch.setattr("neocarta._cli.config.load_dotenv", lambda *_a, **_kw: None)
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("BIGQUERY_DATASET_ID", raising=False)
    result = runner.invoke(cli, ["--json", "bigquery", "schema", "--dry-run"])
    # CLIError("usage_error") → exit code 2 per the AGENTS-CLI map.
    assert result.exit_code == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "usage_error"
    assert "project-id" in payload["error"]["message"].lower()
