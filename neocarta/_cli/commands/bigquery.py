"""``neocarta bigquery ...`` commands.

Two verbs are exposed:

* ``schema`` — wraps :class:`neocarta.connectors.bigquery.BigQuerySchemaConnector`.
* ``logs`` — wraps :class:`neocarta.connectors.bigquery.BigQueryLogsConnector`
  against BigQuery's ``INFORMATION_SCHEMA.JOBS_BY_PROJECT`` view.
"""

from __future__ import annotations

import click

from ...enums import NodeLabel
from ...errors import NeocartaError
from ..config import load_settings, require, resolve
from ..errors import cli_error_from
from ..output import emit_json
from ._common import (
    DEFAULT_SCHEMA_NODE_LABELS,
    _build_embedder,
    _neo4j_driver,
    _require_neo4j_settings,
    _run_embeddings,
)


@click.group()
def bigquery() -> None:
    """Run BigQuery connectors against your warehouse."""


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
    Pass --embeddings to generate description embeddings after load and write
    them back to the graph (off by default). Use --dry-run to print the planned
    ingestion without touching Neo4j or BigQuery. The project ID and dataset ID
    can come from --project-id / --dataset-id flags, or from GCP_PROJECT_ID /
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
                neo4j_driver=driver,
                database_name=settings.neo4j_database,
            )
            connector.ingest(dataset_id=dataset_id)

            if embeddings:
                stderr.print("[dim]Generating embeddings...[/dim]")
                embedder = _build_embedder(settings, driver)
                _run_embeddings(embedder, node_labels)
        except NeocartaError as exc:
            raise cli_error_from(exc) from exc

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
            connector.ingest(
                dataset_id=dataset_id,
                region=region,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                limit=limit,
                drop_failed_queries=drop_failed,
            )

            if embeddings:
                stderr.print("[dim]Generating embeddings...[/dim]")
                embedder = _build_embedder(settings, driver)
                _run_embeddings(embedder, [NodeLabel.TABLE, NodeLabel.COLUMN])
        except NeocartaError as exc:
            raise cli_error_from(exc) from exc

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
