"""Unit tests for ``neocarta snowflake schema`` / ``neocarta snowflake logs``.

The connectors need a live Snowflake account + Neo4j, so these tests cover CLI
plumbing only: --help shape, group/agent-context registration, --dry-run
side-effect-freeness, missing-config errors, the success envelope, secret
handling, and library-error -> exit-code routing. The connector and the
snowflake connection are mocked, so nothing reaches a real warehouse (and the
optional ``snowflake`` extra need not be installed).
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from neocarta._cli import cli
from neocarta._cli.errors import EXIT_CODES
from neocarta.errors import AuthError, ConfigError, Neo4jConnectionError, RateLimitError

_EXTRA_CHECK = "neocarta._cli.commands.snowflake._snowflake_extra_installed"
_CONN_CTX = "neocarta._cli.commands.snowflake._snowflake_connection"
_DRIVER_CTX = "neocarta._cli.commands.snowflake._neo4j_driver"

# Every SNOWFLAKE_* / NEO4J_* var these tests reason about. Cleared before each test
# (autouse below) so a developer's ambient shell exports (e.g. a real
# SNOWFLAKE_PRIVATE_KEY_PATH) can't leak in and flip the resolved auth method —
# each test then sets exactly the vars it needs.
_MANAGED_ENV_VARS = (
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PASSWORD",
    "SNOWFLAKE_ROLE",
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_DATABASE",
    "SNOWFLAKE_SCHEMA",
    "SNOWFLAKE_PRIVATE_KEY_PATH",
    "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE",
    "SNOWFLAKE_AUTHENTICATOR",
    "SNOWFLAKE_TOKEN",
    "NEO4J_URI",
    "NEO4J_USERNAME",
    "NEO4J_PASSWORD",
    "NEO4J_DATABASE",
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Make these CLI tests hermetic against ambient SNOWFLAKE_*/NEO4J_* shell exports."""
    for name in _MANAGED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_group_and_help_document_verbs():
    runner = CliRunner()
    group = runner.invoke(cli, ["snowflake", "--help"])
    assert group.exit_code == 0
    assert "schema" in group.output
    assert "logs" in group.output

    result = runner.invoke(cli, ["snowflake", "schema", "--help"])
    assert result.exit_code == 0
    for token in (
        "--account",
        "--user",
        "--warehouse",
        "--database",
        "--schema",
        "--value-sample-limit",
        "--embeddings",
        "--dry-run",
    ):
        assert token in result.output, f"--help should document {token}"


def test_agent_context_registers_snowflake():
    runner = CliRunner()
    payload = json.loads(runner.invoke(cli, ["agent-context"]).output)
    assert "snowflake" in payload["commands"]
    subcommands = payload["commands"]["snowflake"]["subcommands"]
    assert "schema" in subcommands
    assert "logs" in subcommands
    for env_var in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_PASSWORD", "SNOWFLAKE_DATABASE"):
        assert env_var in payload["env_vars"]


@pytest.fixture
def _dry_env(monkeypatch):
    """Set the minimum for a schema dry-run (database + schema) and isolate .env."""
    monkeypatch.setattr("neocarta._cli.config.load_dotenv", lambda *_a, **_kw: None)
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "MYDB")
    monkeypatch.setenv("SNOWFLAKE_SCHEMA", "PUBLIC")


@pytest.mark.usefixtures("_dry_env")
def test_schema_dry_run_emits_json_without_secrets(monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_PASSWORD", "super-secret")
    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "snowflake", "schema", "--dry-run"])
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)["snowflake_schema"]
    assert body["dry_run"] is True
    assert body["database"] == "MYDB"
    assert body["schema"] == "PUBLIC"
    assert body["value_sample_limit"] == 10
    assert "snowflake_extra_installed" in body
    assert "super-secret" not in result.output


@pytest.mark.usefixtures("_dry_env")
def test_logs_dry_run_emits_json(monkeypatch):
    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "snowflake", "logs", "--dry-run", "--limit", "25"])
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)["snowflake_logs"]
    assert body["dry_run"] is True
    assert body["database"] == "MYDB"
    assert body["limit"] == 25
    assert body["drop_failed_queries"] is True


def test_missing_database_fails_with_usage_error(monkeypatch):
    monkeypatch.setattr("neocarta._cli.config.load_dotenv", lambda *_a, **_kw: None)
    monkeypatch.delenv("SNOWFLAKE_DATABASE", raising=False)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["--json", "snowflake", "schema", "--schema", "PUBLIC", "--dry-run"]
    )
    assert result.exit_code == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "usage_error"


@pytest.mark.usefixtures("_dry_env")
def test_missing_snowflake_extra_fails_with_usage_error():
    """A missing `snowflake` extra is a clean usage_error, not an ImportError traceback."""
    runner = CliRunner()
    with (
        patch(_EXTRA_CHECK, return_value=False),
        patch("neocarta.connectors.snowflake.SnowflakeSchemaConnector") as mock_connector,
    ):
        result = runner.invoke(cli, ["--json", "snowflake", "schema"])

    assert result.exit_code == EXIT_CODES["usage_error"]["code"], result.output
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "usage_error"
    assert "neocarta[snowflake]" in payload["error"]["suggestion"]
    mock_connector.assert_not_called()


@pytest.fixture
def _cli_env(monkeypatch):
    """Populate every env var required for the command to start a real run."""
    monkeypatch.setattr("neocarta._cli.config.load_dotenv", lambda *_a, **_kw: None)
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "password")
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "xy12345")
    monkeypatch.setenv("SNOWFLAKE_USER", "me")
    monkeypatch.setenv("SNOWFLAKE_PASSWORD", "sf-secret")
    monkeypatch.setenv("SNOWFLAKE_WAREHOUSE", "WH")
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "MYDB")
    monkeypatch.setenv("SNOWFLAKE_SCHEMA", "PUBLIC")


@pytest.mark.usefixtures("_cli_env")
def test_schema_success_invokes_connector_and_hides_secret():
    runner = CliRunner()
    with (
        patch(_EXTRA_CHECK, return_value=True),
        patch(_DRIVER_CTX) as mock_driver_ctx,
        patch(_CONN_CTX) as mock_conn_ctx,
        patch(
            "neocarta.connectors.snowflake.SnowflakeSchemaConnector", return_value=MagicMock()
        ) as mock_connector,
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False
        mock_conn_ctx.return_value.__enter__.return_value = MagicMock()
        mock_conn_ctx.return_value.__exit__.return_value = False
        result = runner.invoke(cli, ["--json", "snowflake", "schema"])

    assert result.exit_code == 0, result.output
    out = result.output
    payload = json.loads(out[out.index("{") :])
    assert payload["snowflake_schema"]["status"] == "succeeded"
    mock_connector.return_value.ingest.assert_called_once_with(schema="PUBLIC")
    assert mock_connector.call_args.kwargs["database"] == "MYDB"
    assert mock_connector.call_args.kwargs["value_sample_limit"] == 10
    assert "sf-secret" not in result.output


@pytest.mark.usefixtures("_cli_env")
def test_logs_success_invokes_connector():
    runner = CliRunner()
    with (
        patch(_EXTRA_CHECK, return_value=True),
        patch(_DRIVER_CTX) as mock_driver_ctx,
        patch(_CONN_CTX) as mock_conn_ctx,
        patch(
            "neocarta.connectors.snowflake.SnowflakeLogsConnector", return_value=MagicMock()
        ) as mock_connector,
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False
        mock_conn_ctx.return_value.__enter__.return_value = MagicMock()
        mock_conn_ctx.return_value.__exit__.return_value = False
        # extractor stats read from the (mocked) connector's extractor
        mock_connector.return_value.extractor.query_info = []
        mock_connector.return_value.extractor.table_info = []
        mock_connector.return_value.extractor.column_info = []
        result = runner.invoke(
            cli,
            [
                "--json",
                "snowflake",
                "logs",
                "--limit",
                "10",
                "--schema",
                "PUBLIC",
                "--include-failed-queries",
                "--start-date",
                "2024-01-01 00:00:00",
                "--end-date",
                "2024-01-31 23:59:59",
            ],
        )

    assert result.exit_code == 0, result.output
    mock_connector.return_value.ingest.assert_called_once()
    kw = mock_connector.return_value.ingest.call_args.kwargs
    assert kw["limit"] == 10
    assert kw["schema"] == "PUBLIC"
    assert kw["drop_failed_queries"] is False  # --include-failed-queries flips the default
    assert kw["start_timestamp"] == "2024-01-01 00:00:00"
    assert kw["end_timestamp"] == "2024-01-31 23:59:59"


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
def test_routes_library_errors_to_exit_codes(error, expected_exit_code):
    """Every NeocartaError raised from the connector becomes its CLI code."""
    runner = CliRunner()
    with (
        patch(_EXTRA_CHECK, return_value=True),
        patch(_DRIVER_CTX) as mock_driver_ctx,
        patch(_CONN_CTX) as mock_conn_ctx,
        patch("neocarta.connectors.snowflake.SnowflakeSchemaConnector", side_effect=error),
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False
        mock_conn_ctx.return_value.__enter__.return_value = MagicMock()
        mock_conn_ctx.return_value.__exit__.return_value = False
        result = runner.invoke(cli, ["snowflake", "schema"])

    assert result.exit_code == expected_exit_code, (
        f"{type(error).__name__} should exit {expected_exit_code}, got {result.exit_code}."
    )


# --- alternative auth methods (key-pair / authenticator) ------------------------


@pytest.fixture
def _kp_env(monkeypatch):
    """Neo4j + Snowflake connection env WITHOUT a password (auth set per-test)."""
    monkeypatch.setattr("neocarta._cli.config.load_dotenv", lambda *_a, **_kw: None)
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "password")
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "xy12345")
    monkeypatch.setenv("SNOWFLAKE_USER", "me")
    monkeypatch.setenv("SNOWFLAKE_WAREHOUSE", "WH")
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "MYDB")
    monkeypatch.setenv("SNOWFLAKE_SCHEMA", "PUBLIC")
    monkeypatch.delenv("SNOWFLAKE_PASSWORD", raising=False)
    monkeypatch.delenv("SNOWFLAKE_PRIVATE_KEY_PATH", raising=False)
    monkeypatch.delenv("SNOWFLAKE_AUTHENTICATOR", raising=False)


@pytest.mark.usefixtures("_kp_env")
def test_keypair_auth_builds_connection_without_password(monkeypatch, tmp_path):
    """SNOWFLAKE_PRIVATE_KEY_PATH -> connect(private_key_file=...), no password required."""
    pytest.importorskip("snowflake.connector")  # patching connect needs the driver importable
    key = tmp_path / "rsa_key.p8"
    key.write_text("-----BEGIN PRIVATE KEY-----\ndummy\n-----END PRIVATE KEY-----\n")
    monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY_PATH", str(key))
    runner = CliRunner()
    with (
        patch(_EXTRA_CHECK, return_value=True),
        patch(_DRIVER_CTX) as mock_driver_ctx,
        patch("snowflake.connector.connect", return_value=MagicMock()) as mock_connect,
        patch("neocarta.connectors.snowflake.SnowflakeSchemaConnector", return_value=MagicMock()),
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False
        result = runner.invoke(cli, ["--json", "snowflake", "schema", "--no-embeddings"])

    assert result.exit_code == 0, result.output
    kwargs = mock_connect.call_args.kwargs
    assert kwargs["private_key_file"] == str(key)
    assert kwargs["account"] == "xy12345"
    assert "password" not in kwargs  # key-pair path must not send a password


@pytest.mark.usefixtures("_cli_env")
def test_password_auth_builds_connection():
    """The default password path builds connect(password=...) through real _snowflake_connection."""
    pytest.importorskip("snowflake.connector")
    runner = CliRunner()
    with (
        patch(_EXTRA_CHECK, return_value=True),
        patch(_DRIVER_CTX) as mock_driver_ctx,
        patch("snowflake.connector.connect", return_value=MagicMock()) as mock_connect,
        patch("neocarta.connectors.snowflake.SnowflakeSchemaConnector", return_value=MagicMock()),
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False
        result = runner.invoke(cli, ["--json", "snowflake", "schema", "--no-embeddings"])

    assert result.exit_code == 0, result.output
    kwargs = mock_connect.call_args.kwargs
    assert kwargs["password"] == "sf-secret"  # from _cli_env, unwrapped inline  # noqa: S105
    assert "private_key_file" not in kwargs
    assert "authenticator" not in kwargs


@pytest.mark.usefixtures("_kp_env")
def test_authenticator_auth_builds_connection(monkeypatch):
    """SNOWFLAKE_AUTHENTICATOR -> connect(authenticator=...), no password required."""
    pytest.importorskip("snowflake.connector")
    monkeypatch.setenv("SNOWFLAKE_AUTHENTICATOR", "externalbrowser")
    runner = CliRunner()
    with (
        patch(_EXTRA_CHECK, return_value=True),
        patch(_DRIVER_CTX) as mock_driver_ctx,
        patch("snowflake.connector.connect", return_value=MagicMock()) as mock_connect,
        patch("neocarta.connectors.snowflake.SnowflakeSchemaConnector", return_value=MagicMock()),
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False
        result = runner.invoke(cli, ["--json", "snowflake", "schema", "--no-embeddings"])

    assert result.exit_code == 0, result.output
    kwargs = mock_connect.call_args.kwargs
    assert kwargs["authenticator"] == "externalbrowser"
    assert "password" not in kwargs


@pytest.mark.usefixtures("_kp_env")
def test_no_auth_configured_fails_usage_error():
    """No password / key-pair / authenticator -> clean usage_error, connector not built."""
    runner = CliRunner()
    with (
        patch(_EXTRA_CHECK, return_value=True),
        patch(_DRIVER_CTX) as mock_driver_ctx,
        patch("neocarta.connectors.snowflake.SnowflakeSchemaConnector") as mock_connector,
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False
        result = runner.invoke(cli, ["--json", "snowflake", "schema"])

    assert result.exit_code == EXIT_CODES["usage_error"]["code"], result.output
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "usage_error"
    assert "SNOWFLAKE_PRIVATE_KEY_PATH" in payload["error"]["suggestion"]
    mock_connector.assert_not_called()


@pytest.mark.usefixtures("_kp_env")
def test_keypair_missing_file_fails_usage_error(monkeypatch):
    """A SNOWFLAKE_PRIVATE_KEY_PATH that isn't a file -> usage_error."""
    monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY_PATH", "/no/such/key.p8")
    runner = CliRunner()
    with (
        patch(_EXTRA_CHECK, return_value=True),
        patch(_DRIVER_CTX) as mock_driver_ctx,
        patch("neocarta.connectors.snowflake.SnowflakeSchemaConnector") as mock_connector,
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False
        result = runner.invoke(cli, ["--json", "snowflake", "schema"])

    assert result.exit_code == EXIT_CODES["usage_error"]["code"], result.output
    assert json.loads(result.stdout)["error"]["code"] == "usage_error"
    mock_connector.assert_not_called()


@pytest.mark.usefixtures("_kp_env")
def test_connection_failure_maps_to_clean_cli_error(monkeypatch, tmp_path):
    """A snowflake.connector connection error becomes a clean CLIError, not a raw traceback."""
    sferr = pytest.importorskip("snowflake.connector.errors")
    key = tmp_path / "rsa_key.p8"
    key.write_text("-----BEGIN PRIVATE KEY-----\ndummy\n-----END PRIVATE KEY-----\n")
    monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY_PATH", str(key))
    runner = CliRunner()
    with (
        patch(_EXTRA_CHECK, return_value=True),
        patch(_DRIVER_CTX) as mock_driver_ctx,
        patch(
            "snowflake.connector.connect",
            side_effect=sferr.DatabaseError("JWT token is invalid"),
        ),
        patch("neocarta.connectors.snowflake.SnowflakeSchemaConnector") as mock_connector,
    ):
        mock_driver_ctx.return_value.__enter__.return_value = MagicMock()
        mock_driver_ctx.return_value.__exit__.return_value = False
        result = runner.invoke(cli, ["--json", "snowflake", "schema", "--no-embeddings"])

    assert result.exit_code == EXIT_CODES["auth_error"]["code"], result.output
    assert json.loads(result.stdout)["error"]["code"] == "auth_error"
    mock_connector.return_value.ingest.assert_not_called()


def test_multiple_auth_methods_warns(caplog, tmp_path):
    """When >1 auth method is configured, precedence picks one and a warning is logged."""
    import logging

    from neocarta._cli.commands.snowflake import _auth_method, _resolve_connection_settings
    from neocarta._cli.config import CLISettings

    key = tmp_path / "rsa_key.p8"
    key.write_text("-----BEGIN PRIVATE KEY-----\ndummy\n-----END PRIVATE KEY-----\n")
    # Both key-pair AND password configured (e.g. a stale leftover SNOWFLAKE_PASSWORD).
    settings = CLISettings(
        snowflake_account="a",
        snowflake_user="u",
        snowflake_warehouse="w",
        snowflake_private_key_path=str(key),
        snowflake_password="leftover",  # noqa: S106
    )
    with caplog.at_level(logging.WARNING, logger="neocarta._cli.commands.snowflake"):
        _resolve_connection_settings(settings, account=None, user=None, warehouse=None, role=None)

    assert _auth_method(settings) == "key_pair"  # precedence: key-pair wins
    warnings = [
        r.getMessage() for r in caplog.records if "Multiple Snowflake auth" in r.getMessage()
    ]
    assert warnings, "expected a warning naming the overridden methods"
    assert "SNOWFLAKE_PASSWORD" in warnings[0]
    assert "SNOWFLAKE_PRIVATE_KEY_PATH" in warnings[0]
