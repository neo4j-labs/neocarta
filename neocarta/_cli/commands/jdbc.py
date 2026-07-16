"""``neocarta jdbc ...`` commands.

One verb is exposed:

* ``schema`` — wraps :class:`neocarta.connectors.jdbc.JdbcSchemaConnector`,
  extracting relational schema metadata (databases, schemas, tables, columns,
  and foreign-key references) from any JDBC-accessible database via SchemaCrawler
  and loading it into the Neo4j semantic graph.
"""

from __future__ import annotations

import click

from ...errors import NeocartaError
from ..config import load_settings, require, resolve
from ..errors import cli_error_from
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


@click.group()
def jdbc() -> None:
    """Run JDBC connectors against a relational database via SchemaCrawler."""


@jdbc.command("schema")
@click.option(
    "--jdbc-url",
    default=None,
    help="JDBC connection URL, e.g. jdbc:postgresql://host:5432/mydb. Overrides JDBC_URL.",
)
@click.option(
    "--jdbc-driver",
    default=None,
    help="Fully-qualified JDBC driver class, e.g. org.postgresql.Driver. Overrides JDBC_DRIVER.",
)
@click.option(
    "--jdbc-driver-jar",
    default=None,
    help="Filesystem path to the JDBC driver JAR. Overrides JDBC_DRIVER_JAR.",
)
@click.option(
    "--schemacrawler-jar",
    default=None,
    help="Path/classpath glob to the SchemaCrawler distribution JARs. Overrides SCHEMACRAWLER_JAR.",
)
@click.option(
    "--db-user",
    default=None,
    help="Database username. Overrides JDBC_USER.",
)
@click.option(
    "--source-database-name",
    default=None,
    help=(
        "Name for the graph Database node; required when it cannot be derived "
        "from the JDBC URL (e.g. Oracle SID, SQL Server URLs). Overrides "
        "JDBC_SOURCE_DATABASE_NAME."
    ),
)
@click.option(
    "--platform",
    default=None,
    help="Hosting platform for the graph Database node, e.g. AWS_RDS. Overrides JDBC_PLATFORM.",
)
@click.option(
    "--service",
    default=None,
    help=(
        "Database service/engine for the graph Database node; defaults to the "
        "product SchemaCrawler reports. Overrides JDBC_SERVICE."
    ),
)
@click.option(
    "--timeout",
    type=int,
    default=None,
    help="Maximum seconds to wait for the SchemaCrawler subprocess (default: 120). "
    "Overrides JDBC_TIMEOUT.",
)
@click.option(
    "--schema",
    "schemas",
    multiple=True,
    help="Schema name to include; repeatable. Omit to include all schemas.",
)
@click.option(
    "--embeddings/--no-embeddings",
    "embeddings",
    default=False,
    help="Generate embeddings for ingested nodes after ingest (default: disabled).",
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
    help="Print the planned ingestion without touching Neo4j.",
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
def jdbc_schema(
    ctx: click.Context,
    *,
    jdbc_url: str | None,
    jdbc_driver: str | None,
    jdbc_driver_jar: str | None,
    schemacrawler_jar: str | None,
    db_user: str | None,
    source_database_name: str | None,
    platform: str | None,
    service: str | None,
    timeout: int | None,
    schemas: tuple[str, ...],
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
    """Ingest JDBC schema metadata into the Neo4j semantic graph.

    Shells out to SchemaCrawler (Java) to read databases, schemas, tables,
    columns, and foreign-key references from any JDBC-accessible database and
    loads them into Neo4j. Connection inputs come from the flags or the JDBC_*
    env vars; the password is read only from JDBC_PASSWORD, never a flag. When
    --embeddings is enabled, description embeddings are generated and written
    back to the graph (requires provider credentials, e.g. OPENAI_API_KEY); the
    default is disabled. Pass --dry-run to print the planned ingestion without
    touching Neo4j.

    Requires Java 11+, a SchemaCrawler distribution JAR, and a JDBC driver JAR on
    the host; see neocarta/connectors/jdbc/README.md.
    """
    settings = load_settings()
    _apply_neo4j_overrides(
        settings,
        neo4j_uri=neo4j_uri,
        neo4j_username=neo4j_username,
        neo4j_database=neo4j_database,
    )
    jdbc_url = require("--jdbc-url", resolve(jdbc_url, settings.jdbc_url), env_var="JDBC_URL")
    jdbc_driver = require(
        "--jdbc-driver", resolve(jdbc_driver, settings.jdbc_driver), env_var="JDBC_DRIVER"
    )
    jdbc_driver_jar = require(
        "--jdbc-driver-jar",
        resolve(jdbc_driver_jar, settings.jdbc_driver_jar),
        env_var="JDBC_DRIVER_JAR",
    )
    schemacrawler_jar = require(
        "--schemacrawler-jar",
        resolve(schemacrawler_jar, settings.schemacrawler_jar),
        env_var="SCHEMACRAWLER_JAR",
    )
    db_user = resolve(db_user, settings.jdbc_user)
    source_database_name = resolve(source_database_name, settings.jdbc_source_database_name)
    platform = resolve(platform, settings.jdbc_platform)
    service = resolve(service, settings.jdbc_service)
    timeout = resolve(timeout, settings.jdbc_timeout)
    schema_filter = list(schemas) or None

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
            "jdbc_schema": {
                "dry_run": True,
                "jdbc_url": jdbc_url,
                "jdbc_driver": jdbc_driver,
                "jdbc_driver_jar": jdbc_driver_jar,
                "schemacrawler_jar": schemacrawler_jar,
                "db_user": db_user,
                "source_database_name": source_database_name,
                "platform": platform,
                "service": service,
                "timeout": timeout,
                "schemas": schema_filter,
                "database": settings.neo4j_database,
                "embeddings": embeddings,
                "embedding_model": settings.embedding_model if embeddings else None,
                "embedding_dimensions": settings.embedding_dimensions if embeddings else None,
                "embedding_batch_size": settings.embedding_batch_size if embeddings else None,
            }
        }
        if as_json:
            emit_json(payload)
        else:
            stdout.print(payload)
        return

    _require_neo4j_settings(settings)

    # Lazy import: keep the connector dependency off the --help / --dry-run path.
    from ...connectors.jdbc import JdbcSchemaConnector  # noqa: PLC0415

    with _neo4j_driver(settings) as driver:
        try:
            connector = JdbcSchemaConnector(
                jdbc_url=jdbc_url,
                jdbc_driver=jdbc_driver,
                jdbc_driver_jar=jdbc_driver_jar,
                schemacrawler_jar=schemacrawler_jar,
                neo4j_driver=driver,
                database_name=settings.neo4j_database,
                source_database_name=source_database_name,
                db_user=db_user,
                # Unwrap the secret inline so the raw password never lives in a
                # named local; the connector forwards it to SchemaCrawler via env.
                db_password=(
                    settings.jdbc_password.get_secret_value() if settings.jdbc_password else None
                ),
                platform=platform,
                service=service,
                timeout=timeout,
            )
            with cli_status(stderr, "Ingesting JDBC schema metadata..."):
                connector.ingest(schemas=schema_filter)

            if embeddings:
                embedder = _build_embedder(settings, driver)
                with cli_status(stderr, "Generating embeddings..."):
                    _run_embeddings(embedder, node_labels, batch_size=settings.embedding_batch_size)
        except NeocartaError as exc:
            raise cli_error_from(exc) from exc

    payload = {
        "jdbc_schema": {
            "jdbc_url": jdbc_url,
            "database": settings.neo4j_database,
            "schemas": schema_filter,
            "embeddings": embeddings,
            "status": "succeeded",
        }
    }
    if as_json:
        emit_json(payload)
    else:
        stdout.print(
            f"Ingested JDBC schema metadata from [bold]{jdbc_url}[/bold] into "
            f"[bold]{settings.neo4j_database}[/bold] "
            f"({'with' if embeddings else 'without'} embeddings)."
        )
