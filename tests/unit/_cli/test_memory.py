"""Unit tests for ``neocarta memory init-indexes``."""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from neocarta._cli import cli
from neocarta._cli.errors import EXIT_CODES


@pytest.fixture
def _cli_env(monkeypatch):
    """Populate the Neo4j env vars the ``init-indexes`` command validates before starting."""
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "password")


def test_memory_group_help_lists_init_indexes():
    runner = CliRunner()
    result = runner.invoke(cli, ["memory", "--help"])
    assert result.exit_code == 0
    assert "init-indexes" in result.output


def test_init_indexes_help_documents_flags():
    runner = CliRunner()
    result = runner.invoke(cli, ["memory", "init-indexes", "--help"])
    assert result.exit_code == 0
    output = result.output
    for token in ("--embedding-model", "--embedding-dimensions", "--dry-run", "--json"):
        assert token in output, f"--help should document {token}"


@pytest.mark.usefixtures("_cli_env")
def test_init_indexes_dry_run_emits_json_and_does_not_touch_neo4j():
    runner = CliRunner()
    with (
        patch("neocarta._cli.commands.memory._neo4j_driver") as mock_driver_ctx,
        patch("neocarta._cli.commands.memory._build_embedder") as mock_build_embedder,
        patch("neocarta.ingest.indexes.create_memory_indexes") as mock_create_indexes,
    ):
        result = runner.invoke(cli, ["--json", "memory", "init-indexes", "--dry-run"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    body = payload["memory_init_indexes"]
    assert body["dry_run"] is True
    assert body["indexes"] == ["phrase_vector_index", "phrase_full_text_index"]
    assert body["embedding_model"] == "text-embedding-3-small"
    # Dry-run must never touch Neo4j or probe the embedder.
    mock_driver_ctx.assert_not_called()
    mock_build_embedder.assert_not_called()
    mock_create_indexes.assert_not_called()


@pytest.mark.usefixtures("_cli_env")
def test_init_indexes_dry_run_reflects_embedding_overrides():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--json",
            "memory",
            "init-indexes",
            "--dry-run",
            "--embedding-model",
            "text-embedding-3-large",
            "--embedding-dimensions",
            "256",
        ],
    )

    assert result.exit_code == 0, result.output
    body = json.loads(result.output)["memory_init_indexes"]
    assert body["embedding_model"] == "text-embedding-3-large"
    assert body["embedding_dimensions"] == 256


def test_init_indexes_missing_neo4j_config_fails_with_usage_error(monkeypatch):
    # python-dotenv walks up from CWD and would find the repo's own .env; stub it
    # and clear the Neo4j vars so this test sees them as truly absent.
    monkeypatch.setattr("neocarta._cli.config.load_dotenv", lambda *_a, **_kw: None)
    for var in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"):
        monkeypatch.delenv(var, raising=False)

    runner = CliRunner()
    with patch("neocarta.ingest.indexes.create_memory_indexes") as mock_create_indexes:
        result = runner.invoke(cli, ["--json", "memory", "init-indexes"])

    assert result.exit_code == EXIT_CODES["usage_error"]["code"], result.output
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "usage_error"
    assert "NEO4J" in payload["error"]["message"]
    mock_create_indexes.assert_not_called()


@pytest.mark.usefixtures("_cli_env")
def test_init_indexes_success_creates_indexes_with_probed_dimensions():
    runner = CliRunner()
    mock_embedder = MagicMock()
    mock_embedder._probe_dimensions_sync.return_value = 1536
    mock_summaries = {"phrase_vector_index": {}, "phrase_full_text_index": {}}

    with (
        patch("neocarta._cli.commands.memory._neo4j_driver") as mock_driver_ctx,
        patch("neocarta._cli.commands.memory._build_embedder", return_value=mock_embedder),
        patch(
            "neocarta.ingest.indexes.create_memory_indexes", return_value=mock_summaries
        ) as mock_create_indexes,
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False

        result = runner.invoke(cli, ["--json", "memory", "init-indexes"])

    assert result.exit_code == 0, result.output
    out = result.output
    payload = json.loads(out[out.index("{") :])
    body = payload["memory_init_indexes"]
    assert body["status"] == "succeeded"
    assert body["dimensions"] == 1536
    assert body["indexes"] == mock_summaries
    mock_create_indexes.assert_called_once()
    assert mock_create_indexes.call_args.kwargs["dimensions"] == 1536


@pytest.mark.usefixtures("_cli_env")
def test_init_indexes_probe_failure_maps_to_upstream_error():
    runner = CliRunner()
    mock_embedder = MagicMock()
    mock_embedder._probe_dimensions_sync.side_effect = RuntimeError("invalid model")

    with (
        patch("neocarta._cli.commands.memory._neo4j_driver") as mock_driver_ctx,
        patch("neocarta._cli.commands.memory._build_embedder", return_value=mock_embedder),
        patch("neocarta.ingest.indexes.create_memory_indexes") as mock_create_indexes,
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False

        result = runner.invoke(cli, ["--json", "memory", "init-indexes"])

    assert result.exit_code == EXIT_CODES["upstream_error"]["code"], result.output
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "upstream_error"
    assert "OPENAI_API_KEY" in payload["error"]["suggestion"]
    mock_create_indexes.assert_not_called()
