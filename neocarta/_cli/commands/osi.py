"""``neocarta osi ...`` commands.

One verb is exposed:

* ``ingest`` — wraps :class:`neocarta.connectors.osi.OsiConnector`, loading an
  OSI (Open Semantic Interchange) YAML semantic model from a local path or an
  HTTP(S) URL into the Neo4j semantic graph.
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
def osi() -> None:
    """Run OSI connectors against an OSI YAML semantic model."""


@osi.command("ingest")
@click.option(
    "--spec-source",
    default=None,
    help="Path or URL to the OSI YAML spec. Overrides OSI_SPEC_SOURCE.",
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
def osi_ingest(
    ctx: click.Context,
    *,
    spec_source: str | None,
    embeddings: bool,
    embedding_model: str | None,
    dry_run: bool,
    json_flag: bool,
) -> None:
    """Ingest an OSI YAML semantic model into the Neo4j semantic graph.

    Reads an OSI spec from a local filesystem path or an http(s):// URL and
    loads its semantic model into Neo4j (``OsiSemanticModel``, ``OsiTable``,
    ``OsiColumn``, ``Query``, ``Metric``, ``Join``, and aspect nodes; synonyms
    in ``ai_context`` are upserted as ``BusinessTerm`` nodes). When --embeddings
    is enabled, description embeddings are generated and written back to the
    graph; the default is disabled. Pass --dry-run to print the planned
    ingestion without touching Neo4j. The spec source can come from the
    --spec-source flag or the OSI_SPEC_SOURCE env var.
    """
    settings = load_settings()
    spec_source = require(
        "--spec-source",
        resolve(spec_source, settings.osi_spec_source),
        env_var="OSI_SPEC_SOURCE",
    )
    if embedding_model is not None:
        settings.embedding_model = embedding_model

    stdout = ctx.obj["stdout"]
    stderr = ctx.obj["stderr"]
    as_json = ctx.obj["as_json"] or json_flag
    node_labels = list(DEFAULT_SCHEMA_NODE_LABELS)

    if dry_run:
        payload = {
            "osi_ingest": {
                "dry_run": True,
                "spec_source": spec_source,
                "database": settings.neo4j_database,
                "embeddings": embeddings,
                "embedding_model": settings.embedding_model if embeddings else None,
            }
        }
        if as_json:
            emit_json(payload)
        else:
            stdout.print(payload)
        return

    _require_neo4j_settings(settings)

    # Lazy import: keep the connector dependency off the --help / --dry-run path.
    from ...connectors.osi import OsiConnector  # noqa: PLC0415

    stderr.print("[dim]Starting OSI connector...[/dim]")

    with _neo4j_driver(settings) as driver:
        try:
            connector = OsiConnector(
                neo4j_driver=driver,
                database_name=settings.neo4j_database,
            )
            connector.ingest(spec_source)

            if embeddings:
                stderr.print("[dim]Generating embeddings...[/dim]")
                embedder = _build_embedder(settings, driver)
                embedder.run(node_labels=node_labels)
        except NeocartaError as exc:
            raise cli_error_from(exc) from exc

    payload = {
        "osi_ingest": {
            "spec_source": spec_source,
            "database": settings.neo4j_database,
            "embeddings": embeddings,
            "status": "succeeded",
        }
    }
    if as_json:
        emit_json(payload)
    else:
        stdout.print(
            f"Ingested OSI semantic model from [bold]{spec_source}[/bold] into "
            f"[bold]{settings.neo4j_database}[/bold] "
            f"({'with' if embeddings else 'without'} embeddings)."
        )
