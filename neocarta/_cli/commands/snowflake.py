"""``neocarta snowflake ...`` commands.

Two verbs are exposed:

* ``schema`` — wraps :class:`neocarta.connectors.snowflake.SnowflakeSchemaConnector`
  to load ``Database``/``Schema``/``Table``/``Column``/``Value`` from a database's
  ``INFORMATION_SCHEMA`` (and ``SHOW ... KEYS``).
* ``logs`` — wraps :class:`neocarta.connectors.snowflake.SnowflakeLogsConnector`
  against ``SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY``.

Both build (and own) a ``snowflake.connector`` connection from the ``SNOWFLAKE_*``
settings and pass it to the caller-owned-connection connector. Requires the
``snowflake`` extra (``pip install 'neocarta[snowflake]'``).
"""

from __future__ import annotations

import contextlib
import importlib.util
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import click

from ...enums import NodeLabel
from ...errors import NeocartaError
from ..config import load_settings, require, resolve
from ..errors import CLIError, cli_error_from
from ..output import cli_status, emit_json
from ._common import (
    DEFAULT_SCHEMA_NODE_LABELS,
    _apply_neo4j_overrides,
    _build_embedder,
    _neo4j_driver,
    _require_neo4j_settings,
    _run_embeddings,
    neo4j_options,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from snowflake.connector import SnowflakeConnection

    from ..config import CLISettings

logger = logging.getLogger(__name__)

# Import name the optional ``snowflake`` extra provides.
# Reaching this command already implies the ``cli`` extra is installed.
_SNOWFLAKE_IMPORT = "snowflake.connector"


def _snowflake_extra_installed() -> bool:
    """Return True if the ``snowflake`` extra's connector is importable.

    Uses :func:`importlib.util.find_spec` (no real import / side effects), so the
    check can run on the --dry-run path too. A missing parent namespace raises
    ``ModuleNotFoundError`` and is treated as not-installed.
    """
    try:
        return importlib.util.find_spec(_SNOWFLAKE_IMPORT) is not None
    except ModuleNotFoundError:
        return False


def _auth_method(settings: CLISettings) -> str:
    """Return which Snowflake auth method is configured (precedence order).

    An empty ``SNOWFLAKE_PASSWORD`` counts as unset (``"none"``), so a blank value
    can't masquerade as configured auth and slip past the require-one-of check.
    """
    if settings.snowflake_private_key_path:
        return "key_pair"
    if settings.snowflake_authenticator:
        return "authenticator"
    if settings.snowflake_password is not None and settings.snowflake_password.get_secret_value():
        return "password"
    return "none"


@contextlib.contextmanager
def _snowflake_connection(settings: CLISettings) -> Iterator[SnowflakeConnection]:
    """Yield a ``snowflake.connector`` connection for ``settings`` and close it on exit.

    The CLI builds and owns the connection it hands to the caller-owned-connection
    connector. Supports three auth methods, in precedence order:

    1. **Key-pair** (``SNOWFLAKE_PRIVATE_KEY_PATH`` [+ ``SNOWFLAKE_PRIVATE_KEY_PASSPHRASE``])
       — recommended for MFA-enforced accounts, where password auth is blocked for
       programmatic access.
    2. **Authenticator** (``SNOWFLAKE_AUTHENTICATOR``, e.g. ``externalbrowser`` /
       ``oauth`` / ``PROGRAMMATIC_ACCESS_TOKEN``) with an optional ``SNOWFLAKE_TOKEN``.
    3. **Password** (``SNOWFLAKE_PASSWORD``).

    All secrets are unwrapped via ``.get_secret_value()`` only at the ``connect``
    call (never bound to a named local variable).
    """
    import snowflake.connector as snowflake_connector  # noqa: PLC0415

    # _resolve_connection_settings has validated account/user/warehouse + one auth method.
    assert settings.snowflake_account is not None  # noqa: S101
    assert settings.snowflake_user is not None  # noqa: S101
    connect_kwargs: dict[str, object] = {
        "account": settings.snowflake_account,
        "user": settings.snowflake_user,
        "warehouse": settings.snowflake_warehouse,
        "database": settings.snowflake_database,
    }
    if settings.snowflake_role:
        connect_kwargs["role"] = settings.snowflake_role

    # Secrets (passphrase / token / password) are unwrapped inline into the connect()
    # call via anonymous dict-splats and are never bound to a named local variable
    # (the connect_kwargs dict below holds only non-secret connection parameters).
    method = _auth_method(settings)
    try:
        if method == "key_pair":
            connect_kwargs["private_key_file"] = settings.snowflake_private_key_path
            connection = snowflake_connector.connect(
                **connect_kwargs,
                **(
                    {
                        "private_key_file_pwd": settings.snowflake_private_key_passphrase.get_secret_value()
                    }
                    if settings.snowflake_private_key_passphrase is not None
                    else {}
                ),
            )
        elif method == "authenticator":
            connect_kwargs["authenticator"] = settings.snowflake_authenticator
            connection = snowflake_connector.connect(
                **connect_kwargs,
                **(
                    {"token": settings.snowflake_token.get_secret_value()}
                    if settings.snowflake_token is not None
                    else {}
                ),
                **(
                    {"password": settings.snowflake_password.get_secret_value()}
                    if settings.snowflake_password is not None
                    else {}
                ),
            )
        else:  # password
            assert settings.snowflake_password is not None  # noqa: S101
            connection = snowflake_connector.connect(
                password=settings.snowflake_password.get_secret_value(), **connect_kwargs
            )
    except snowflake_connector.errors.Error as exc:
        # A failed connection (bad key / account / token / MFA policy / network) must
        # surface as a clean CLIError, not a raw snowflake.connector traceback. Classify
        # by exception class only (never message text, which may contain sensitive detail).
        names = {klass.__name__ for klass in type(exc).__mro__}
        transient = {"OperationalError", "InternalError", "ServiceUnavailableError"}
        is_transient = bool(names & transient)
        raise CLIError(
            "upstream_error" if is_transient else "auth_error",
            "Failed to connect to Snowflake.",
            suggestion=(
                "Verify SNOWFLAKE_ACCOUNT / SNOWFLAKE_USER and your auth: for key-pair, "
                "the matching public key must be registered on the user "
                "(ALTER USER <user> SET RSA_PUBLIC_KEY=...); for password/token, that the "
                "credential is valid and your account permits it for programmatic access."
            ),
            retryable=is_transient,
            details={"error_type": type(exc).__name__},
        ) from exc
    try:
        yield connection
    finally:
        connection.close()


def _snowflake_connection_options(func: click.decorators.FC) -> click.decorators.FC:
    """Attach the shared ``SNOWFLAKE_*`` connection options to a command.

    The password is intentionally **not** a flag: it is read only from
    SNOWFLAKE_PASSWORD, so the raw secret never lands in a named local variable,
    shell history, or the process list — mirroring the JDBC_PASSWORD discipline.
    """
    func = click.option(
        "--role", default=None, help="Snowflake role to assume. Overrides SNOWFLAKE_ROLE."
    )(func)
    func = click.option(
        "--warehouse",
        default=None,
        help="Snowflake warehouse for the metadata queries. Overrides SNOWFLAKE_WAREHOUSE.",
    )(func)
    func = click.option(
        "--user", default=None, help="Snowflake username. Overrides SNOWFLAKE_USER."
    )(func)
    return click.option(
        "--account",
        default=None,
        help="Snowflake account identifier. Overrides SNOWFLAKE_ACCOUNT.",
    )(func)


def _resolve_connection_settings(
    settings: CLISettings,
    *,
    account: str | None,
    user: str | None,
    warehouse: str | None,
    role: str | None,
) -> None:
    """Fold the ``SNOWFLAKE_*`` connection flags onto ``settings`` and validate them.

    At least one auth method must be configured (key-pair / authenticator / password).
    When more than one is set, the highest-precedence one wins (key-pair >
    authenticator > password) and a warning is logged, so a stale/leftover env var
    silently overriding the intended method is surfaced rather than hidden. Secrets
    are validated for presence but never bound to a local — they are unwrapped inline
    in :func:`_snowflake_connection`.
    """
    settings.snowflake_account = require(
        "--account", resolve(account, settings.snowflake_account), env_var="SNOWFLAKE_ACCOUNT"
    )
    settings.snowflake_user = require(
        "--user", resolve(user, settings.snowflake_user), env_var="SNOWFLAKE_USER"
    )
    settings.snowflake_warehouse = require(
        "--warehouse",
        resolve(warehouse, settings.snowflake_warehouse),
        env_var="SNOWFLAKE_WAREHOUSE",
    )
    settings.snowflake_role = resolve(role, settings.snowflake_role)

    # Require one auth method (an empty password counts as unset — see _auth_method).
    # Password auth is blocked for programmatic access on MFA-enforced accounts, so
    # key-pair / authenticator are first-class alternatives.
    if _auth_method(settings) == "none":
        raise CLIError(
            "usage_error",
            "No Snowflake authentication configured.",
            suggestion=(
                "Set one of SNOWFLAKE_PRIVATE_KEY_PATH (key-pair; recommended for "
                "MFA-enforced accounts), SNOWFLAKE_AUTHENTICATOR (+ SNOWFLAKE_TOKEN), "
                "or SNOWFLAKE_PASSWORD."
            ),
        )
    if (
        settings.snowflake_private_key_path
        and not Path(settings.snowflake_private_key_path).is_file()
    ):
        raise CLIError(
            "usage_error",
            f"SNOWFLAKE_PRIVATE_KEY_PATH is not a readable file: {settings.snowflake_private_key_path}",
            suggestion="Point SNOWFLAKE_PRIVATE_KEY_PATH at your PEM private key file.",
        )

    # Precedence picks exactly one method, but silently ignoring the others is
    # confusing (e.g. a stale SNOWFLAKE_PASSWORD when the user meant key-pair). Warn —
    # don't fail — when more than one is configured, naming the one actually used.
    configured = [
        env
        for env, present in (
            ("SNOWFLAKE_PRIVATE_KEY_PATH", bool(settings.snowflake_private_key_path)),
            ("SNOWFLAKE_AUTHENTICATOR", bool(settings.snowflake_authenticator)),
            (
                "SNOWFLAKE_PASSWORD",
                settings.snowflake_password is not None
                and settings.snowflake_password.get_secret_value() != "",
            ),
        )
        if present
    ]
    if len(configured) > 1:
        logger.warning(
            "Multiple Snowflake auth methods configured (%s); using %s by precedence "
            "(key-pair > authenticator > password). Unset the others to silence this.",
            ", ".join(configured),
            _auth_method(settings),
        )


@click.group()
def snowflake() -> None:
    """Run Snowflake connectors against your warehouse."""


@snowflake.command("schema")
@_snowflake_connection_options
@click.option(
    "--database", default=None, help="Snowflake database to ingest. Overrides SNOWFLAKE_DATABASE."
)
@click.option(
    "--schema", default=None, help="Snowflake schema to ingest. Overrides SNOWFLAKE_SCHEMA."
)
@click.option(
    "--value-sample-limit",
    type=int,
    default=10,
    help="Distinct sample values to read per column (0 disables value sampling).",
)
@click.option(
    "--embeddings/--no-embeddings",
    "embeddings",
    default=False,
    help="Generate embeddings for ingested nodes after load (default: disabled).",
)
@click.option(
    "--embedding-model",
    default=None,
    help="Embedding model id in LiteLLM format (default: text-embedding-3-small).",
)
@click.option(
    "--embedding-dimensions",
    type=int,
    default=None,
    help="Embedding vector dimensions (default: auto-detected from the model).",
)
@click.option(
    "--embedding-batch-size",
    type=int,
    default=None,
    help="Nodes per embedding batch (default: 100). Overrides EMBEDDING_BATCH_SIZE.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print the planned ingestion without touching Neo4j or Snowflake.",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Emit JSON on stdout. Also accepted as a top-level flag.",
)
@neo4j_options
@click.pass_context
def snowflake_schema(
    ctx: click.Context,
    *,
    account: str | None,
    user: str | None,
    warehouse: str | None,
    role: str | None,
    database: str | None,
    schema: str | None,
    value_sample_limit: int,
    embeddings: bool,
    embedding_model: str | None,
    embedding_dimensions: int | None,
    embedding_batch_size: int | None,
    dry_run: bool,
    json_flag: bool,
    neo4j_uri: str | None,
    neo4j_username: str | None,
    neo4j_database: str | None,
) -> None:
    """Extract Snowflake schema metadata into the Neo4j semantic graph.

    Loads Database, Schema, Table, Column, and Value nodes plus their
    relationships from a database's INFORMATION_SCHEMA (foreign/primary keys come
    from SHOW ... KEYS). Pass --embeddings to generate description embeddings after
    load. Use --value-sample-limit 0 to skip reading table data. Use --dry-run to
    print the planned ingestion without touching Neo4j or Snowflake. Connection
    settings come from --account / --user / --warehouse / --role / --database /
    --schema flags or the matching SNOWFLAKE_* env vars; the password is read only
    from SNOWFLAKE_PASSWORD. Requires the ``snowflake`` extra
    (``pip install 'neocarta[snowflake]'``).
    """
    settings = load_settings()
    _apply_neo4j_overrides(
        settings,
        neo4j_uri=neo4j_uri,
        neo4j_username=neo4j_username,
        neo4j_database=neo4j_database,
    )
    settings.snowflake_database = require(
        "--database", resolve(database, settings.snowflake_database), env_var="SNOWFLAKE_DATABASE"
    )
    schema = require(
        "--schema", resolve(schema, settings.snowflake_schema), env_var="SNOWFLAKE_SCHEMA"
    )
    if embedding_model is not None:
        settings.embedding_model = embedding_model
    if embedding_dimensions is not None:
        settings.embedding_dimensions = embedding_dimensions
    if embedding_batch_size is not None:
        settings.embedding_batch_size = embedding_batch_size

    stdout = ctx.obj["stdout"]
    stderr = ctx.obj["stderr"]
    as_json = ctx.obj["as_json"] or json_flag
    node_labels = list(DEFAULT_SCHEMA_NODE_LABELS)

    if dry_run:
        payload = {
            "snowflake_schema": {
                "dry_run": True,
                "account": resolve(account, settings.snowflake_account),
                "database": settings.snowflake_database,
                "schema": schema,
                "value_sample_limit": value_sample_limit,
                "neo4j_database": settings.neo4j_database,
                "embeddings": embeddings,
                "embedding_model": settings.embedding_model if embeddings else None,
                "embedding_dimensions": settings.embedding_dimensions if embeddings else None,
                "embedding_batch_size": settings.embedding_batch_size if embeddings else None,
                "node_labels": [label.value for label in node_labels],
                "auth_method": _auth_method(settings),
                # find_spec only — does not import the connector.
                "snowflake_extra_installed": _snowflake_extra_installed(),
            }
        }
        if as_json:
            emit_json(payload)
        else:
            stdout.print(payload)
        return

    if not _snowflake_extra_installed():
        raise CLIError(
            "usage_error",
            "The Snowflake connector extra is not installed.",
            suggestion=(
                "Install it with: pip install 'neocarta[snowflake]' "
                "(or 'neocarta[cli,snowflake]' for the CLI and connector together)."
            ),
        )

    _require_neo4j_settings(settings)
    _resolve_connection_settings(
        settings, account=account, user=user, warehouse=warehouse, role=role
    )

    # Lazy import: the connector (and its pandas dependency) only load when the command runs.
    from ...connectors.snowflake import SnowflakeSchemaConnector  # noqa: PLC0415

    with _neo4j_driver(settings) as driver, _snowflake_connection(settings) as connection:
        try:
            connector = SnowflakeSchemaConnector(
                connection=connection,
                database=settings.snowflake_database,
                neo4j_driver=driver,
                database_name=settings.neo4j_database,
                value_sample_limit=value_sample_limit,
            )
            with cli_status(stderr, "Ingesting Snowflake schema..."):
                connector.ingest(schema=schema)

            if embeddings:
                embedder = _build_embedder(settings, driver)
                with cli_status(stderr, "Generating embeddings..."):
                    _run_embeddings(embedder, node_labels, batch_size=settings.embedding_batch_size)
        except NeocartaError as exc:
            raise cli_error_from(exc) from exc

    payload = {
        "snowflake_schema": {
            "database": settings.snowflake_database,
            "schema": schema,
            "neo4j_database": settings.neo4j_database,
            "embeddings": embeddings,
            "node_labels": [label.value for label in node_labels],
            "status": "succeeded",
        }
    }
    if as_json:
        emit_json(payload)
    else:
        stdout.print(
            f"Loaded Snowflake schema for [bold]{settings.snowflake_database}.{schema}[/bold] "
            f"into [bold]{settings.neo4j_database}[/bold] "
            f"({'with' if embeddings else 'without'} embeddings)."
        )


@snowflake.command("logs")
@_snowflake_connection_options
@click.option(
    "--database",
    default=None,
    help="Snowflake database whose queries to ingest. Overrides SNOWFLAKE_DATABASE.",
)
@click.option(
    "--schema",
    default=None,
    help="Schema to filter queries by (optional). Overrides SNOWFLAKE_SCHEMA.",
)
@click.option(
    "--start-date",
    "start_timestamp",
    default=None,
    help="Inclusive start timestamp (ISO 8601). Default: 30 days ago.",
)
@click.option(
    "--end-date",
    "end_timestamp",
    default=None,
    help="Exclusive end timestamp (ISO 8601). Default: now.",
)
@click.option("--limit", type=int, default=100, help="Maximum number of queries to extract.")
@click.option(
    "--include-failed-queries",
    is_flag=True,
    default=False,
    help="Include queries that failed (default: exclude).",
)
@click.option(
    "--embeddings/--no-embeddings",
    "embeddings",
    default=False,
    help="Generate embeddings for ingested nodes after load (default: disabled for logs).",
)
@click.option(
    "--embedding-model",
    default=None,
    help="Embedding model id in LiteLLM format (default: text-embedding-3-small).",
)
@click.option(
    "--embedding-dimensions",
    type=int,
    default=None,
    help="Embedding vector dimensions (default: auto-detected from the model).",
)
@click.option(
    "--embedding-batch-size",
    type=int,
    default=None,
    help="Nodes per embedding batch (default: 100). Overrides EMBEDDING_BATCH_SIZE.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print the planned ingestion without touching Neo4j or Snowflake.",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Emit JSON on stdout. Also accepted as a top-level flag.",
)
@neo4j_options
@click.pass_context
def snowflake_logs(
    ctx: click.Context,
    *,
    account: str | None,
    user: str | None,
    warehouse: str | None,
    role: str | None,
    database: str | None,
    schema: str | None,
    start_timestamp: str | None,
    end_timestamp: str | None,
    limit: int,
    include_failed_queries: bool,
    embeddings: bool,
    embedding_model: str | None,
    embedding_dimensions: int | None,
    embedding_batch_size: int | None,
    dry_run: bool,
    json_flag: bool,
    neo4j_uri: str | None,
    neo4j_username: str | None,
    neo4j_database: str | None,
) -> None:
    """Extract Snowflake query logs from SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY.

    Loads Query and CTE nodes plus the table/column references each query touches.
    Use --start-date / --end-date to scope the time window, --limit to cap how
    many queries are pulled, --schema to restrict to (and resolve names against) a
    schema, and --include-failed-queries to retain queries that errored. Reading
    ACCOUNT_USAGE needs access to the SNOWFLAKE database and has ingest latency.
    Connection settings come from the --account / ... flags or the SNOWFLAKE_* env
    vars; the password is read only from SNOWFLAKE_PASSWORD. Requires the
    ``snowflake`` extra (``pip install 'neocarta[snowflake]'``).
    """
    settings = load_settings()
    _apply_neo4j_overrides(
        settings,
        neo4j_uri=neo4j_uri,
        neo4j_username=neo4j_username,
        neo4j_database=neo4j_database,
    )
    settings.snowflake_database = require(
        "--database", resolve(database, settings.snowflake_database), env_var="SNOWFLAKE_DATABASE"
    )
    schema = resolve(schema, settings.snowflake_schema)
    if embedding_model is not None:
        settings.embedding_model = embedding_model
    if embedding_dimensions is not None:
        settings.embedding_dimensions = embedding_dimensions
    if embedding_batch_size is not None:
        settings.embedding_batch_size = embedding_batch_size

    stdout = ctx.obj["stdout"]
    stderr = ctx.obj["stderr"]
    as_json = ctx.obj["as_json"] or json_flag
    drop_failed = not include_failed_queries

    if dry_run:
        payload = {
            "snowflake_logs": {
                "dry_run": True,
                "account": resolve(account, settings.snowflake_account),
                "database": settings.snowflake_database,
                "schema": schema,
                "limit": limit,
                "start_timestamp": start_timestamp,
                "end_timestamp": end_timestamp,
                "drop_failed_queries": drop_failed,
                "neo4j_database": settings.neo4j_database,
                "embeddings": embeddings,
                "embedding_model": settings.embedding_model if embeddings else None,
                "embedding_dimensions": settings.embedding_dimensions if embeddings else None,
                "embedding_batch_size": settings.embedding_batch_size if embeddings else None,
                "auth_method": _auth_method(settings),
                "snowflake_extra_installed": _snowflake_extra_installed(),
            }
        }
        if as_json:
            emit_json(payload)
        else:
            stdout.print(payload)
        return

    if not _snowflake_extra_installed():
        raise CLIError(
            "usage_error",
            "The Snowflake connector extra is not installed.",
            suggestion=(
                "Install it with: pip install 'neocarta[snowflake]' "
                "(or 'neocarta[cli,snowflake]' for the CLI and connector together)."
            ),
        )

    _require_neo4j_settings(settings)
    _resolve_connection_settings(
        settings, account=account, user=user, warehouse=warehouse, role=role
    )

    # Lazy import: the connector (and its pandas dependency) only load when the command runs.
    from ...connectors.snowflake import SnowflakeLogsConnector  # noqa: PLC0415

    with _neo4j_driver(settings) as driver, _snowflake_connection(settings) as connection:
        try:
            connector = SnowflakeLogsConnector(
                connection=connection,
                database=settings.snowflake_database,
                neo4j_driver=driver,
                database_name=settings.neo4j_database,
            )
            with cli_status(stderr, "Ingesting Snowflake query logs..."):
                connector.ingest(
                    schema=schema,
                    start_timestamp=start_timestamp,
                    end_timestamp=end_timestamp,
                    limit=limit,
                    drop_failed_queries=drop_failed,
                )

            if embeddings:
                embedder = _build_embedder(settings, driver)
                with cli_status(stderr, "Generating embeddings..."):
                    _run_embeddings(
                        embedder,
                        [NodeLabel.TABLE, NodeLabel.COLUMN],
                        batch_size=settings.embedding_batch_size,
                    )
        except NeocartaError as exc:
            raise cli_error_from(exc) from exc

        extractor = connector.extractor
        result = {
            "database": settings.snowflake_database,
            "schema": schema,
            "neo4j_database": settings.neo4j_database,
            "queries": len(extractor.query_info),
            "tables_referenced": len(extractor.table_info),
            "columns_referenced": len(extractor.column_info),
            "drop_failed_queries": drop_failed,
            "embeddings": embeddings,
            "status": "succeeded",
        }

    payload = {"snowflake_logs": result}
    if as_json:
        emit_json(payload)
    else:
        stdout.print(
            f"Loaded {result['queries']} queries referencing "
            f"{result['tables_referenced']} tables / {result['columns_referenced']} columns "
            f"into [bold]{settings.neo4j_database}[/bold]."
        )
