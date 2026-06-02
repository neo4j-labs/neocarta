"""``neocarta csv ...`` commands.

One verb is exposed:

* ``load`` — wraps :class:`neocarta.connectors.csv.CSVConnector`, loading metadata
  from a directory of CSV files into the Neo4j semantic graph.
"""

from __future__ import annotations

import click

from ...errors import NeocartaError
from ..config import load_settings, require, resolve
from ..errors import cli_error_from
from ..output import emit_json
from ._common import (
    DEFAULT_SCHEMA_NODE_LABELS,
    _build_embedder,
    _neo4j_driver,
    _require_neo4j_settings,
)


@click.group()
def csv() -> None:
    """Run CSV connectors against a directory of metadata files."""


@csv.command("ingest")
@click.option(
    "--csv-directory",
    default=None,
    help="Directory containing the CSV metadata files. Overrides CSV_DIRECTORY.",
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
    help="Print the planned ingestion without touching Neo4j.",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Emit JSON on stdout. Also accepted as a top-level flag.",
)
@click.pass_context
def csv_ingest(
    ctx: click.Context,
    *,
    csv_directory: str | None,
    embeddings: bool,
    embedding_model: str | None,
    embedding_dimensions: int | None,
    dry_run: bool,
    json_flag: bool,
) -> None:
    """Ingest metadata from CSV files into the Neo4j semantic graph.

    Ingests every entity CSV found in the directory (Database, Schema, Table,
    Column, Value, Query, and glossary nodes) plus their relationships; files
    that are not present are skipped. When --embeddings is enabled, description
    embeddings are generated and written back to the graph (requires
    OPENAI_API_KEY); the default is disabled. Pass --dry-run to print the
    planned ingestion without touching Neo4j. The directory can come from the
    --csv-directory flag or the CSV_DIRECTORY env var.
    """
    settings = load_settings()
    csv_directory = require(
        "--csv-directory",
        resolve(csv_directory, settings.csv_directory),
        env_var="CSV_DIRECTORY",
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
            "csv_ingest": {
                "dry_run": True,
                "csv_directory": csv_directory,
                "database": settings.neo4j_database,
                "embeddings": embeddings,
                "embedding_model": settings.embedding_model if embeddings else None,
                "embedding_dimensions": settings.embedding_dimensions if embeddings else None,
            }
        }
        if as_json:
            emit_json(payload)
        else:
            stdout.print(payload)
        return

    _require_neo4j_settings(settings)

    # Lazy import: keep the connector dependency off the --help / --dry-run path.
    from ...connectors.csv import CSVConnector  # noqa: PLC0415

    stderr.print("[dim]Starting CSV connector...[/dim]")

    with _neo4j_driver(settings) as driver:
        try:
            connector = CSVConnector(
                csv_directory=csv_directory,
                neo4j_driver=driver,
                database_name=settings.neo4j_database,
            )
            connector.run()

            if embeddings:
                stderr.print("[dim]Generating embeddings...[/dim]")
                embedder = _build_embedder(settings, driver)
                embedder.run(node_labels=node_labels)
        except NeocartaError as exc:
            raise cli_error_from(exc) from exc

    payload = {
        "csv_ingest": {
            "csv_directory": csv_directory,
            "database": settings.neo4j_database,
            "embeddings": embeddings,
            "status": "succeeded",
        }
    }
    if as_json:
        emit_json(payload)
    else:
        stdout.print(
            f"Ingested CSV metadata from [bold]{csv_directory}[/bold] into "
            f"[bold]{settings.neo4j_database}[/bold] "
            f"({'with' if embeddings else 'without'} embeddings)."
        )
