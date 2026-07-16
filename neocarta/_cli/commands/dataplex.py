"""``neocarta dataplex ...`` commands.

Two verbs are exposed, mirroring ``bigquery schema`` / ``bigquery logs`` — the
noun is the source (``dataplex``) and the verb is the subgraph component to
ingest:

* ``schema`` — wraps :class:`neocarta.connectors.dataplex.DataplexSchemaConnector`
  to load BigQuery schema metadata (``Database``, ``Schema``, ``Table``,
  ``Column``) from the Dataplex Universal Catalog.
* ``glossary`` — wraps :class:`neocarta.connectors.dataplex.DataplexGlossaryConnector`
  to load the Dataplex business glossary (``Glossary``, ``Category``,
  ``BusinessTerm``) and the catalog↔glossary entry links that back
  ``TAGGED_WITH`` edges.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click

from ...enums import NodeLabel
from ...errors import NeocartaError
from ..config import load_settings, require, resolve
from ..errors import cli_error_from
from ..output import cli_status, emit_json
from ._common import (
    _apply_neo4j_overrides,
    _build_embedder,
    _neo4j_driver,
    _require_neo4j_settings,
    _run_embeddings,
    neo4j_options,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from neo4j import Driver

    from ..config import CLISettings


@click.group()
def dataplex() -> None:
    """Run Dataplex connectors against your Google Cloud catalog."""


def _run_ingest(
    ctx: click.Context,
    *,
    verb: str,
    settings: CLISettings,
    plan: dict[str, Any],
    embeddings: bool,
    node_labels: list[NodeLabel],
    json_flag: bool,
    dry_run: bool,
    make_connector: Callable[[Driver], Any],
    ingest_kwargs: dict[str, Any],
) -> None:
    """Shared driver→ingest→embed→emit flow for the dataplex verbs.

    ``make_connector`` lazily constructs the verb's connector for a given Neo4j
    driver; ``ingest_kwargs`` are forwarded to ``connector.ingest(...)``. The
    JSON/human envelope is keyed ``dataplex_{verb}``.
    """
    stdout = ctx.obj["stdout"]
    stderr = ctx.obj["stderr"]
    as_json = ctx.obj["as_json"] or json_flag
    payload_key = f"dataplex_{verb}"

    body: dict[str, Any] = {**plan, "database": settings.neo4j_database, "embeddings": embeddings}
    if embeddings:
        body["embedding_model"] = settings.embedding_model
        body["embedding_dimensions"] = settings.embedding_dimensions
        body["embedding_batch_size"] = settings.embedding_batch_size
        body["node_labels"] = [label.value for label in node_labels]

    if dry_run:
        payload = {payload_key: {"dry_run": True, **body}}
        if as_json:
            emit_json(payload)
        else:
            stdout.print(payload)
        return

    _require_neo4j_settings(settings)

    with _neo4j_driver(settings) as driver:
        try:
            with cli_status(stderr, f"Ingesting Dataplex {verb} metadata..."):
                connector = make_connector(driver)
                connector.ingest(**ingest_kwargs)

            if embeddings:
                embedder = _build_embedder(settings, driver)
                with cli_status(stderr, "Generating embeddings..."):
                    _run_embeddings(embedder, node_labels, batch_size=settings.embedding_batch_size)
        except NeocartaError as exc:
            raise cli_error_from(exc) from exc

    payload = {payload_key: {**body, "status": "succeeded"}}
    if as_json:
        emit_json(payload)
    else:
        stdout.print(
            f"Ingested Dataplex {verb} metadata for [bold]{plan['project_id']}[/bold] into "
            f"[bold]{settings.neo4j_database}[/bold] "
            f"({'with' if embeddings else 'without'} embeddings)."
        )


@dataplex.command("schema")
@click.option("--project-id", default=None, help="GCP project ID. Overrides GCP_PROJECT_ID.")
@click.option(
    "--project-number",
    default=None,
    help="GCP project number. Overrides GCP_PROJECT_NUMBER.",
)
@click.option(
    "--dataplex-location",
    default=None,
    help="Dataplex location, e.g. 'us'. Overrides DATAPLEX_LOCATION.",
)
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
    help="LiteLLM embedding model name (default: text-embedding-3-small).",
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
    help="Print the planned ingestion without touching Neo4j or Dataplex.",
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
def dataplex_schema(
    ctx: click.Context,
    *,
    project_id: str | None,
    project_number: str | None,
    dataplex_location: str | None,
    dataset_id: str | None,
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
    """Ingest Dataplex BigQuery schema metadata into the Neo4j semantic graph.

    Loads Database, Schema, Table, and Column nodes plus their relationships
    from the Dataplex Universal Catalog. When --embeddings is enabled, Table and
    Column description embeddings are generated via LiteLLM and written back.
    Pass --dry-run to print the planned ingestion without touching Neo4j or
    Dataplex. Project ID, project number, location, and dataset come from the
    flags or the GCP_PROJECT_ID / GCP_PROJECT_NUMBER / DATAPLEX_LOCATION /
    BIGQUERY_DATASET_ID env vars.
    """
    settings = load_settings()
    _apply_neo4j_overrides(
        settings,
        neo4j_uri=neo4j_uri,
        neo4j_username=neo4j_username,
        neo4j_database=neo4j_database,
    )
    project_id = require(
        "--project-id", resolve(project_id, settings.gcp_project_id), env_var="GCP_PROJECT_ID"
    )
    project_number = require(
        "--project-number",
        resolve(project_number, settings.gcp_project_number),
        env_var="GCP_PROJECT_NUMBER",
    )
    dataplex_location = require(
        "--dataplex-location",
        resolve(dataplex_location, settings.dataplex_location),
        env_var="DATAPLEX_LOCATION",
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
    if embedding_batch_size is not None:
        settings.embedding_batch_size = embedding_batch_size

    def make_connector(driver: Driver) -> Any:
        # Lazy imports: heavy GCP / connector deps only load when the command runs.
        from google.cloud import dataplex_v1  # noqa: PLC0415

        from ...connectors.dataplex import DataplexSchemaConnector  # noqa: PLC0415

        return DataplexSchemaConnector(
            catalog_client=dataplex_v1.CatalogServiceClient(),
            project_id=project_id,
            project_number=project_number,
            dataplex_location=dataplex_location,
            neo4j_driver=driver,
            database_name=settings.neo4j_database,
        )

    _run_ingest(
        ctx,
        verb="schema",
        settings=settings,
        plan={
            "project_id": project_id,
            "project_number": project_number,
            "dataplex_location": dataplex_location,
            "dataset_id": dataset_id,
        },
        embeddings=embeddings,
        node_labels=[NodeLabel.TABLE, NodeLabel.COLUMN],
        json_flag=json_flag,
        dry_run=dry_run,
        make_connector=make_connector,
        ingest_kwargs={"dataset_id": dataset_id},
    )


@dataplex.command("glossary")
@click.option("--project-id", default=None, help="GCP project ID. Overrides GCP_PROJECT_ID.")
@click.option(
    "--project-number",
    default=None,
    help="GCP project number. Overrides GCP_PROJECT_NUMBER.",
)
@click.option(
    "--dataplex-location",
    default=None,
    help="Dataplex location, e.g. 'us'. Overrides DATAPLEX_LOCATION.",
)
@click.option(
    "--entry-links/--no-entry-links",
    "entry_links",
    default=True,
    help="Also load catalog entry links as TAGGED_WITH edges (default: enabled). "
    "Requires the schema nodes to already exist (run `dataplex schema` first).",
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
    help="LiteLLM embedding model name (default: text-embedding-3-small).",
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
    help="Print the planned ingestion without touching Neo4j or Dataplex.",
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
def dataplex_glossary(
    ctx: click.Context,
    *,
    project_id: str | None,
    project_number: str | None,
    dataplex_location: str | None,
    entry_links: bool,
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
    """Ingest the Dataplex business glossary into the Neo4j semantic graph.

    Loads Glossary, Category, and BusinessTerm nodes plus their relationships,
    and (with --entry-links, the default) the catalog entry links as
    (:Column|:Table)-[:TAGGED_WITH]->(:BusinessTerm) edges — these attach to
    schema nodes, so run `dataplex schema` first for the tags to land. When
    --embeddings is enabled, BusinessTerm description embeddings are generated
    via LiteLLM and written back. Pass --dry-run to print the planned ingestion
    without touching Neo4j or Dataplex. Project ID, project number, and location
    come from the flags or the GCP_PROJECT_ID / GCP_PROJECT_NUMBER /
    DATAPLEX_LOCATION env vars.
    """
    settings = load_settings()
    _apply_neo4j_overrides(
        settings,
        neo4j_uri=neo4j_uri,
        neo4j_username=neo4j_username,
        neo4j_database=neo4j_database,
    )
    project_id = require(
        "--project-id", resolve(project_id, settings.gcp_project_id), env_var="GCP_PROJECT_ID"
    )
    project_number = require(
        "--project-number",
        resolve(project_number, settings.gcp_project_number),
        env_var="GCP_PROJECT_NUMBER",
    )
    dataplex_location = require(
        "--dataplex-location",
        resolve(dataplex_location, settings.dataplex_location),
        env_var="DATAPLEX_LOCATION",
    )
    if embedding_model is not None:
        settings.embedding_model = embedding_model
    if embedding_dimensions is not None:
        settings.embedding_dimensions = embedding_dimensions
    if embedding_batch_size is not None:
        settings.embedding_batch_size = embedding_batch_size

    def make_connector(driver: Driver) -> Any:
        # Lazy imports: heavy GCP / connector deps only load when the command runs.
        from google.cloud import dataplex_v1  # noqa: PLC0415

        from ...connectors.dataplex import DataplexGlossaryConnector  # noqa: PLC0415

        return DataplexGlossaryConnector(
            glossary_client=dataplex_v1.BusinessGlossaryServiceClient(),
            project_id=project_id,
            project_number=project_number,
            dataplex_location=dataplex_location,
            neo4j_driver=driver,
            database_name=settings.neo4j_database,
        )

    _run_ingest(
        ctx,
        verb="glossary",
        settings=settings,
        plan={
            "project_id": project_id,
            "project_number": project_number,
            "dataplex_location": dataplex_location,
            "entry_links": entry_links,
        },
        embeddings=embeddings,
        node_labels=[NodeLabel.BUSINESS_TERM],
        json_flag=json_flag,
        dry_run=dry_run,
        make_connector=make_connector,
        ingest_kwargs={"include_entry_links": entry_links},
    )
