"""``neocarta databricks ...`` commands.

One verb is exposed:

* ``embed`` — runs :mod:`neocarta.enrichment.embeddings` against the Neo4j graph
  the Databricks Spark ingest job already produced, generating description
  embeddings and writing them back. This is the **external-mode** hand-off as a
  first-class command.

The Spark schema ingest itself is *not* a CLI verb: it writes through the Neo4j
Spark Connector and must run as a wheel job on a Databricks cluster, so it
cannot run in-process off-cluster. Inline (in-cluster) embeddings are a setting
on that Spark job, not a CLI flag. This command covers only the in-process
enrichment step, which reads nodes from Neo4j, calls an embedding model, and
writes vectors back.
"""

from __future__ import annotations

import click

from ...errors import NeocartaError
from ..config import load_settings
from ..errors import cli_error_from
from ..output import emit_json
from ._common import (
    DEFAULT_SCHEMA_NODE_LABELS,
    _build_embedder,
    _neo4j_driver,
    _require_neo4j_settings,
)


@click.group()
def databricks() -> None:
    """Enrich a Databricks-ingested graph with embeddings."""


@databricks.command("embed")
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
    help="Print the planned embedding run without touching Neo4j.",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Emit JSON on stdout. Also accepted as a top-level flag.",
)
@click.pass_context
def databricks_embed(
    ctx: click.Context,
    *,
    embedding_model: str | None,
    embedding_dimensions: int | None,
    dry_run: bool,
    json_flag: bool,
) -> None:
    """Generate embeddings for a Databricks-ingested graph and write them back.

    Run this after the Databricks Spark ingest job has produced the schema
    graph in Neo4j. It embeds Database, Schema, Table, and Column descriptions
    with OpenAI (requires OPENAI_API_KEY) and writes the vectors back to the
    matching nodes. Pass --dry-run to print the planned run without touching
    Neo4j. This is the external-mode hand-off; for in-cluster (inline)
    embeddings, enable them on the Spark ingest job instead.
    """
    settings = load_settings()
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
            "databricks_embed": {
                "dry_run": True,
                "database": settings.neo4j_database,
                "embedding_model": settings.embedding_model,
                "embedding_dimensions": settings.embedding_dimensions,
                "node_labels": [label.value for label in node_labels],
            }
        }
        if as_json:
            emit_json(payload)
        else:
            stdout.print(payload)
        return

    _require_neo4j_settings(settings)

    stderr.print("[dim]Generating embeddings...[/dim]")

    with _neo4j_driver(settings) as driver:
        try:
            embedder = _build_embedder(settings, driver)
            embedder.run(node_labels=node_labels)
        except NeocartaError as exc:
            raise cli_error_from(exc) from exc

    payload = {
        "databricks_embed": {
            "database": settings.neo4j_database,
            "embedding_model": settings.embedding_model,
            "embedding_dimensions": settings.embedding_dimensions,
            "node_labels": [label.value for label in node_labels],
            "status": "succeeded",
        }
    }
    if as_json:
        emit_json(payload)
    else:
        stdout.print(
            f"Embedded Databricks graph in [bold]{settings.neo4j_database}[/bold] "
            f"using [bold]{settings.embedding_model}[/bold]."
        )
