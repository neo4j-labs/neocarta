"""``neocarta bigquery ...`` commands.

Two verbs are exposed:

* ``schema`` — wraps :class:`neocarta.connectors.bigquery.BigQuerySchemaConnector`.
* ``logs`` — wraps :class:`neocarta.connectors.bigquery.BigQueryLogsConnector`
  against BigQuery's ``INFORMATION_SCHEMA.JOBS_BY_PROJECT`` view.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import click

from ...enums import NodeLabel
from ...errors import NeocartaError
from ..config import load_settings, require, require_secret, resolve
from ..errors import cli_error_from
from ..output import emit_json

if TYPE_CHECKING:
    from collections.abc import Iterator

    from neo4j import Driver

    from ...enrichment.embeddings import OpenAIEmbeddingsConnector
    from ..config import CLISettings


DEFAULT_SCHEMA_NODE_LABELS = (
    NodeLabel.DATABASE,
    NodeLabel.SCHEMA,
    NodeLabel.TABLE,
    NodeLabel.COLUMN,
)


@click.group()
def bigquery() -> None:
    """Run BigQuery connectors against your warehouse."""


def _require_neo4j_settings(settings: CLISettings) -> None:
    """Validate that Neo4j credentials are configured.

    Returns nothing on purpose: callers must read non-secret fields off the
    settings object directly, and the secret password is only unwrapped inside
    :func:`_neo4j_driver` at the point of use. This keeps the raw password
    out of named local variables and out of CodeQL's reach as a logging-sink
    source.
    """
    require("NEO4J_URI", settings.neo4j_uri, env_var="NEO4J_URI")
    require("NEO4J_USERNAME", settings.neo4j_username, env_var="NEO4J_USERNAME")
    require_secret(
        "NEO4J_PASSWORD",
        settings.neo4j_password,
        env_var="NEO4J_PASSWORD",
    )


@contextlib.contextmanager
def _neo4j_driver(settings: CLISettings) -> Iterator[Driver]:
    """Yield a Neo4j driver for ``settings`` and close it on exit.

    The password is unwrapped inline via ``settings.neo4j_password
    .get_secret_value()`` so the raw secret string is never bound to a named
    local variable in the caller's scope.
    """
    # Lazy import: keeps `neocarta --help` and `agent-context` fast and lets
    # tests run without a Neo4j driver installed.
    from neo4j import GraphDatabase  # noqa: PLC0415

    # _require_neo4j_settings has already raised CLIError if any of these are
    # missing; the asserts narrow the type for the GraphDatabase.driver call.
    assert settings.neo4j_uri is not None  # noqa: S101
    assert settings.neo4j_password is not None  # noqa: S101
    driver = GraphDatabase.driver(
        uri=settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password.get_secret_value()),
    )
    try:
        yield driver
    finally:
        driver.close()


def _build_embedder(
    settings: CLISettings,
    neo4j_driver: Driver,
) -> OpenAIEmbeddingsConnector:
    """Construct an OpenAIEmbeddingsConnector for post-load embedding runs.

    The OpenAI API key is unwrapped from :class:`SecretStr` inline in the
    ``OpenAI(...)`` constructor call, so the raw key is never assigned to a
    named local variable.
    """
    # Lazy import: heavy dependencies are only loaded when embeddings run.
    from openai import OpenAI  # noqa: PLC0415

    from ...enrichment.embeddings import OpenAIEmbeddingsConnector  # noqa: PLC0415

    require_secret(
        "OPENAI_API_KEY",
        settings.openai_api_key,
        env_var="OPENAI_API_KEY",
    )
    # require_secret raised on missing/empty; the assert narrows the type.
    assert settings.openai_api_key is not None  # noqa: S101
    return OpenAIEmbeddingsConnector(
        neo4j_driver=neo4j_driver,
        client=OpenAI(api_key=settings.openai_api_key.get_secret_value()),
        embedding_model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        database_name=settings.neo4j_database,
    )


@bigquery.command("schema")
@click.option("--project-id", default=None, help="GCP project ID. Overrides GCP_PROJECT_ID.")
@click.option(
    "--dataset-id",
    default=None,
    help="BigQuery dataset to ingest. Overrides BIGQUERY_DATASET_ID.",
)
@click.option(
    "--embeddings/--no-embeddings",
    "embeddings",
    default=True,
    help="Generate embeddings for ingested nodes after load (default: enabled).",
)
@click.option(
    "--embedding-model",
    default=None,
    help="OpenAI embedding model name (default: text-embedding-3-small).",
)
@click.option(
    "--embedding-dimensions",
    type=int,
    default=None,
    help="Embedding vector dimensions (default: 768).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print the planned ingestion without touching Neo4j or BigQuery.",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Emit JSON on stdout. Also accepted as a top-level flag.",
)
@click.pass_context
def bigquery_schema(
    ctx: click.Context,
    *,
    project_id: str | None,
    dataset_id: str | None,
    embeddings: bool,
    embedding_model: str | None,
    embedding_dimensions: int | None,
    dry_run: bool,
    json_flag: bool,
) -> None:
    """Extract BigQuery schema metadata into the Neo4j semantic graph.

    Loads Database, Schema, Table, and Column nodes plus their relationships.
    When --embeddings is enabled (default), description embeddings are
    generated and written back to the graph. Pass --no-embeddings to skip the
    OpenAI step, or --dry-run to print the planned ingestion without touching
    Neo4j or BigQuery. The project ID and dataset ID can come from --project-id
    / --dataset-id flags, or from GCP_PROJECT_ID / BIGQUERY_DATASET_ID env vars.
    """
    settings = load_settings()
    project_id = require(
        "--project-id",
        resolve(project_id, settings.gcp_project_id),
        env_var="GCP_PROJECT_ID",
    )
    dataset_id = require(
        "--dataset-id",
        resolve(dataset_id, settings.bigquery_dataset_id),
        env_var="BIGQUERY_DATASET_ID",
    )
    if embedding_model is not None:
        settings.embedding_model = embedding_model
    if embedding_dimensions is not None:
        settings.embedding_dimensions = embedding_dimensions

    stdout = ctx.obj["stdout"]
    stderr = ctx.obj["stderr"]
    as_json = ctx.obj["as_json"] or json_flag
    node_labels = list(DEFAULT_SCHEMA_NODE_LABELS)

    if dry_run:
        payload = {
            "bigquery_schema": {
                "dry_run": True,
                "project_id": project_id,
                "dataset_id": dataset_id,
                "embeddings": embeddings,
                "embedding_model": settings.embedding_model if embeddings else None,
                "embedding_dimensions": settings.embedding_dimensions if embeddings else None,
                "node_labels": [label.value for label in node_labels],
            }
        }
        if as_json:
            emit_json(payload)
        else:
            stdout.print(payload)
        return

    _require_neo4j_settings(settings)

    # Lazy imports: heavy GCP / connector deps are only loaded when the
    # command actually runs, not on --help or --dry-run.
    from google.cloud import bigquery as bq_client  # noqa: PLC0415

    from ...connectors.bigquery import BigQuerySchemaConnector  # noqa: PLC0415

    stderr.print("[dim]Starting BigQuery schema connector...[/dim]")

    with _neo4j_driver(settings) as driver:
        try:
            connector = BigQuerySchemaConnector(
                client=bq_client.Client(project=project_id),
                project_id=project_id,
                dataset_id=dataset_id,
                neo4j_driver=driver,
                database_name=settings.neo4j_database,
            )
            connector.run()
        except NeocartaError as exc:
            raise cli_error_from(exc) from exc

        if embeddings:
            stderr.print("[dim]Generating embeddings...[/dim]")
            embedder = _build_embedder(settings, driver)
            embedder.run(node_labels=node_labels)

    payload = {
        "bigquery_schema": {
            "project_id": project_id,
            "dataset_id": dataset_id,
            "database": settings.neo4j_database,
            "embeddings": embeddings,
            "node_labels": [label.value for label in node_labels],
            "status": "succeeded",
        }
    }
    if as_json:
        emit_json(payload)
    else:
        stdout.print(
            f"Loaded BigQuery schema for [bold]{project_id}.{dataset_id}[/bold] into "
            f"[bold]{settings.neo4j_database}[/bold] "
            f"({'with' if embeddings else 'without'} embeddings)."
        )


@bigquery.command("logs")
@click.option("--project-id", default=None, help="GCP project ID. Overrides GCP_PROJECT_ID.")
@click.option(
    "--dataset-id",
    default=None,
    help="Dataset whose queries to ingest. Overrides BIGQUERY_DATASET_ID.",
)
@click.option(
    "--region", default=None, help="BigQuery region (default: region-us; env: BIGQUERY_REGION)."
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
    help="Inclusive end timestamp (ISO 8601). Default: now.",
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
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print the planned ingestion without touching Neo4j or BigQuery.",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Emit JSON on stdout. Also accepted as a top-level flag.",
)
@click.pass_context
def bigquery_logs(
    ctx: click.Context,
    *,
    project_id: str | None,
    dataset_id: str | None,
    region: str | None,
    start_timestamp: str | None,
    end_timestamp: str | None,
    limit: int,
    include_failed_queries: bool,
    embeddings: bool,
    dry_run: bool,
    json_flag: bool,
) -> None:
    """Extract BigQuery query logs from INFORMATION_SCHEMA.JOBS_BY_PROJECT.

    Loads Query and CTE nodes plus the table/column references each query
    touches. Use --start-date / --end-date to scope the time window, --limit
    to cap how many queries are pulled, and --include-failed-queries to
    retain queries that errored. The project ID and dataset ID can come from
    --project-id / --dataset-id flags, or from GCP_PROJECT_ID /
    BIGQUERY_DATASET_ID env vars.
    """
    settings = load_settings()
    project_id = require(
        "--project-id",
        resolve(project_id, settings.gcp_project_id),
        env_var="GCP_PROJECT_ID",
    )
    dataset_id = require(
        "--dataset-id",
        resolve(dataset_id, settings.bigquery_dataset_id),
        env_var="BIGQUERY_DATASET_ID",
    )
    region = resolve(region, settings.bigquery_region)

    stdout = ctx.obj["stdout"]
    stderr = ctx.obj["stderr"]
    as_json = ctx.obj["as_json"] or json_flag
    drop_failed = not include_failed_queries

    if dry_run:
        payload = {
            "bigquery_logs": {
                "dry_run": True,
                "project_id": project_id,
                "dataset_id": dataset_id,
                "region": region,
                "limit": limit,
                "start_timestamp": start_timestamp,
                "end_timestamp": end_timestamp,
                "drop_failed_queries": drop_failed,
                "embeddings": embeddings,
            }
        }
        if as_json:
            emit_json(payload)
        else:
            stdout.print(payload)
        return

    _require_neo4j_settings(settings)

    # Lazy imports: heavy GCP / connector deps are only loaded when the
    # command actually runs, not on --help or --dry-run.
    from google.cloud import bigquery as bq_client  # noqa: PLC0415

    from ...connectors.bigquery import BigQueryLogsConnector  # noqa: PLC0415

    stderr.print("[dim]Starting BigQuery logs connector...[/dim]")

    with _neo4j_driver(settings) as driver:
        try:
            connector = BigQueryLogsConnector(
                client=bq_client.Client(project=project_id),
                project_id=project_id,
                neo4j_driver=driver,
                database_name=settings.neo4j_database,
            )
            connector.run(
                dataset_id=dataset_id,
                region=region,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                limit=limit,
                drop_failed_queries=drop_failed,
            )
        except NeocartaError as exc:
            raise cli_error_from(exc) from exc

        if embeddings:
            stderr.print("[dim]Generating embeddings...[/dim]")
            embedder = _build_embedder(settings, driver)
            embedder.run(node_labels=[NodeLabel.TABLE, NodeLabel.COLUMN])

        extractor = connector.extractor
        result = {
            "project_id": project_id,
            "dataset_id": dataset_id,
            "region": region,
            "database": settings.neo4j_database,
            "queries": len(extractor.query_info),
            "tables_referenced": len(extractor.table_info),
            "columns_referenced": len(extractor.column_info),
            "drop_failed_queries": drop_failed,
            "embeddings": embeddings,
            "status": "succeeded",
        }

    payload = {"bigquery_logs": result}
    if as_json:
        emit_json(payload)
    else:
        stdout.print(
            f"Loaded {result['queries']} queries referencing "
            f"{result['tables_referenced']} tables / {result['columns_referenced']} columns "
            f"into [bold]{settings.neo4j_database}[/bold]."
        )
