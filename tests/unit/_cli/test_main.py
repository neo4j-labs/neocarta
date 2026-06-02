"""Unit tests for the top-level Click group and global help/version output."""

import json

from click.testing import CliRunner

from neocarta import __version__
from neocarta._cli import cli


def test_help_lists_commands():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "bigquery" in result.output
    assert "csv" in result.output
    assert "agent-context" in result.output
    # Top-level help must document at least one concrete invocation pattern.
    assert "neocarta bigquery" in result.output


def test_version_is_fast_and_clean():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_bad_flag_exits_two():
    runner = CliRunner()
    result = runner.invoke(cli, ["--definitely-not-a-flag"])
    # Click signals usage errors with exit code 2, matching the AGENTS-CLI map.
    assert result.exit_code == 2


def test_bigquery_group_help_lists_verbs():
    runner = CliRunner()
    result = runner.invoke(cli, ["bigquery", "--help"])
    assert result.exit_code == 0
    assert "schema" in result.output
    assert "logs" in result.output


def test_csv_group_help_lists_verbs():
    runner = CliRunner()
    result = runner.invoke(cli, ["csv", "--help"])
    assert result.exit_code == 0
    assert "ingest" in result.output


def test_agent_context_emits_valid_json():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent-context"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert payload["cli_version"] == __version__
    assert "bigquery" in payload["commands"]
    assert "schema" in payload["commands"]["bigquery"]["subcommands"]
    assert "logs" in payload["commands"]["bigquery"]["subcommands"]
    assert "csv" in payload["commands"]
    assert "ingest" in payload["commands"]["csv"]["subcommands"]
    # The exit-code map is part of the public contract; spot-check a known entry.
    assert payload["exit_codes"]["success"]["code"] == 0
    assert payload["exit_codes"]["usage_error"]["code"] == 2
    # Env vars surfaced for agent discovery.
    assert "NEO4J_URI" in payload["env_vars"]
    assert "GCP_PROJECT_ID" in payload["env_vars"]


def test_agent_context_includes_flags_for_bigquery_schema():
    runner = CliRunner()
    result = runner.invoke(cli, ["agent-context"])
    payload = json.loads(result.output)
    flags = payload["commands"]["bigquery"]["subcommands"]["schema"]["flags"]
    assert "--project-id" in flags
    assert "--dataset-id" in flags
    assert "--embeddings" in flags or "--no-embeddings" in flags
    assert "--dry-run" in flags
