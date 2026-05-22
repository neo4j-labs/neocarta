"""Tests for the library-error → CLI-error adapter.

Two layers of coverage:

* ``cli_error_from(...)`` — unit-level: pins the field-by-field mapping
  from :class:`NeocartaError` onto :class:`CLIError`.
* CLI invocation — integration-level: actually runs
  ``neocarta bigquery schema`` / ``logs`` with the connector patched to
  raise each error type, and asserts the right exit code escapes the
  process. This guards against regressions like ``except ValueError``
  drifting out of sync with what the library raises.
"""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from neocarta._cli import cli
from neocarta._cli.errors import EXIT_CODES, CLIError, cli_error_from
from neocarta.errors import (
    AuthError,
    ConfigError,
    EnrichmentError,
    Neo4jConnectionError,
    NeocartaError,
    RateLimitError,
    StateError,
)


def test_config_error_maps_to_validation_exit_code():
    cli_err = cli_error_from(ConfigError("missing project_id"))
    assert isinstance(cli_err, CLIError)
    assert cli_err.code == "validation_error"
    assert cli_err.exit_code == EXIT_CODES["validation_error"]["code"]
    assert cli_err.message == "missing project_id"


def test_state_error_maps_to_validation_exit_code():
    cli_err = cli_error_from(StateError("call extract_glossary_info first"))
    assert cli_err.code == "validation_error"
    assert cli_err.message == "call extract_glossary_info first"


def test_auth_error_maps_to_auth_exit_code():
    cli_err = cli_error_from(AuthError("ADC token expired"))
    assert cli_err.code == "auth_error"
    assert cli_err.exit_code == EXIT_CODES["auth_error"]["code"]


def test_rate_limit_error_preserves_retryable():
    cli_err = cli_error_from(RateLimitError("BQ quota exceeded"))
    assert cli_err.code == "rate_limited"
    assert cli_err.retryable is True


def test_structured_context_forwards_to_envelope():
    src = Neo4jConnectionError(
        "Cannot reach Neo4j.",
        suggestion="Check NEO4J_URI and that the database is running.",
        details={"database": "neo4j", "uri": "bolt://localhost:7687"},
    )
    cli_err = cli_error_from(src)
    assert cli_err.suggestion == "Check NEO4J_URI and that the database is running."
    assert cli_err.details == {"database": "neo4j", "uri": "bolt://localhost:7687"}


# ---------------------------------------------------------------------------
# CLI integration: library errors must escape with the correct exit code
# ---------------------------------------------------------------------------


@pytest.fixture
def _cli_env(monkeypatch):
    """Populate the env vars required for the BigQuery commands to start."""
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "password")
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("BIGQUERY_DATASET_ID", "test_dataset")


@pytest.mark.parametrize(
    ("error", "expected_exit_code"),
    [
        (ConfigError("missing project_id"), EXIT_CODES["validation_error"]["code"]),
        (StateError("call extract_x first"), EXIT_CODES["validation_error"]["code"]),
        (AuthError("ADC token expired"), EXIT_CODES["auth_error"]["code"]),
        (RateLimitError("BQ quota exceeded"), EXIT_CODES["rate_limited"]["code"]),
        (
            Neo4jConnectionError("Cannot reach Neo4j."),
            EXIT_CODES["upstream_error"]["code"],
        ),
    ],
)
@pytest.mark.usefixtures("_cli_env")
def test_bigquery_schema_routes_library_errors_to_exit_codes(
    error: NeocartaError, expected_exit_code: int
):
    """Every NeocartaError raised from the schema connector becomes its CLI code."""
    runner = CliRunner()
    with (
        patch("neocarta._cli.commands.bigquery._neo4j_driver") as mock_driver_ctx,
        patch("google.cloud.bigquery.Client", return_value=MagicMock()),
        patch(
            "neocarta.connectors.bigquery.BigQuerySchemaConnector",
            side_effect=error,
        ),
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False

        result = runner.invoke(cli, ["bigquery", "schema", "--no-embeddings"])

    assert result.exit_code == expected_exit_code, (
        f"{type(error).__name__} should exit {expected_exit_code}, got {result.exit_code}. "
        f"Output: {result.output!r}"
    )


@pytest.mark.usefixtures("_cli_env")
def test_debug_flag_prints_cause_chain():
    """``--debug`` (a top-level flag) should surface the original vendor
    exception via ``__cause__`` instead of hiding it.

    Regression guard: previously the flag was wired up but never read by
    any code, so passing it had no effect on error output.
    """

    class FakeVendorError(RuntimeError):
        pass

    def raise_with_cause(*_args, **_kwargs):
        try:
            raise FakeVendorError("underlying vendor failure")
        except FakeVendorError as cause:
            raise ConfigError("wrapping error") from cause

    runner = CliRunner()
    with (
        patch("neocarta._cli.commands.bigquery._neo4j_driver") as mock_driver_ctx,
        patch("google.cloud.bigquery.Client", return_value=MagicMock()),
        patch(
            "neocarta.connectors.bigquery.BigQuerySchemaConnector",
            side_effect=raise_with_cause,
        ),
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False

        result = runner.invoke(cli, ["--debug", "bigquery", "schema", "--no-embeddings"])

    assert result.exit_code == EXIT_CODES["validation_error"]["code"]
    # The original exception's class and message must appear in stderr
    # when --debug is on. Click's CliRunner mixes stdout/stderr by default.
    assert "FakeVendorError" in result.output
    assert "underlying vendor failure" in result.output


@pytest.mark.usefixtures("_cli_env")
def test_bigquery_schema_routes_embedder_errors_through_adapter(monkeypatch):
    """The try/except must cover the embedder block, not just connector.run().

    Regression guard for an earlier bug where ``embedder.run()`` sat outside
    the ``try`` and any :class:`NeocartaError` from it bypassed the adapter.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    runner = CliRunner()
    mock_embedder = MagicMock()
    mock_embedder.run.side_effect = EnrichmentError("OpenAI embedding call failed.")
    with (
        patch("neocarta._cli.commands.bigquery._neo4j_driver") as mock_driver_ctx,
        patch("google.cloud.bigquery.Client", return_value=MagicMock()),
        patch(
            "neocarta.connectors.bigquery.BigQuerySchemaConnector",
            return_value=MagicMock(),
        ),
        patch(
            "neocarta._cli.commands.bigquery._build_embedder",
            return_value=mock_embedder,
        ),
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False

        result = runner.invoke(cli, ["bigquery", "schema", "--embeddings"])

    assert result.exit_code == EXIT_CODES["upstream_error"]["code"], (
        f"EnrichmentError should exit upstream_error, got {result.exit_code}. "
        f"Output: {result.output!r}"
    )


@pytest.mark.parametrize(
    ("error", "expected_exit_code"),
    [
        (ConfigError("missing project_id"), EXIT_CODES["validation_error"]["code"]),
        (AuthError("ADC token expired"), EXIT_CODES["auth_error"]["code"]),
        (RateLimitError("BQ quota exceeded"), EXIT_CODES["rate_limited"]["code"]),
    ],
)
@pytest.mark.usefixtures("_cli_env")
def test_bigquery_logs_routes_library_errors_to_exit_codes(
    error: NeocartaError, expected_exit_code: int
):
    """Same contract for the logs command."""
    runner = CliRunner()
    with (
        patch("neocarta._cli.commands.bigquery._neo4j_driver") as mock_driver_ctx,
        patch("google.cloud.bigquery.Client", return_value=MagicMock()),
        patch(
            "neocarta.connectors.bigquery.BigQueryLogsConnector",
            side_effect=error,
        ),
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False

        result = runner.invoke(cli, ["bigquery", "logs", "--no-embeddings"])

    assert result.exit_code == expected_exit_code, (
        f"{type(error).__name__} should exit {expected_exit_code}, got {result.exit_code}. "
        f"Output: {result.output!r}"
    )
