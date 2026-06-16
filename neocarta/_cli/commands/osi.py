"""``neocarta osi ...`` commands.

Two verbs are exposed, wrapping :class:`neocarta.connectors.osi.OsiConnector`:

* ``ingest`` — load an OSI (Open Semantic Interchange) YAML semantic model from a
  local path or an HTTP(S) URL into the Neo4j semantic graph.
* ``export`` — read an OSI semantic model back out of Neo4j and write it to an OSI
  YAML file.
"""

from __future__ import annotations

import click

from ...enums import NodeLabel
from ...errors import NeocartaError
from ..config import load_settings, require, resolve
from ..errors import CLIError, cli_error_from
from ..output import cli_status, emit_json
from ._common import (
    DEFAULT_SCHEMA_NODE_LABELS,
    _build_embedder,
    _neo4j_driver,
    _require_neo4j_settings,
    _run_embeddings,
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
@click.pass_context
def osi_ingest(
    ctx: click.Context,
    *,
    spec_source: str | None,
    embeddings: bool,
    embedding_model: str | None,
    embedding_dimensions: int | None,
    embedding_batch_size: int | None,
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
    if embedding_dimensions is not None:
        settings.embedding_dimensions = embedding_dimensions
    if embedding_batch_size is not None:
        settings.embedding_batch_size = embedding_batch_size

    stdout = ctx.obj["stdout"]
    stderr = ctx.obj["stderr"]
    as_json = ctx.obj["as_json"] or json_flag
    # OSI graphs add Metric nodes on top of the shared schema labels. Embedding
    # Metric.description creates metric_vector_index, without which the MCP
    # vector/hybrid metric-search tiers never register on a pure-OSI graph.
    node_labels = [*DEFAULT_SCHEMA_NODE_LABELS, NodeLabel.METRIC]

    if dry_run:
        payload = {
            "osi_ingest": {
                "dry_run": True,
                "spec_source": spec_source,
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
    from ...connectors.osi import OsiConnector  # noqa: PLC0415

    with _neo4j_driver(settings) as driver:
        try:
            connector = OsiConnector(
                neo4j_driver=driver,
                database_name=settings.neo4j_database,
            )
            with cli_status(stderr, "Ingesting OSI semantic model..."):
                connector.ingest(spec_source)

            if embeddings:
                embedder = _build_embedder(settings, driver)
                with cli_status(stderr, "Generating embeddings..."):
                    _run_embeddings(embedder, node_labels, batch_size=settings.embedding_batch_size)
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


@osi.command("export")
@click.option(
    "--semantic-model-name",
    default=None,
    help="Name of the OsiSemanticModel to export. Overrides OSI_SEMANTIC_MODEL_NAME.",
)
@click.option(
    "--output-path",
    default=None,
    help="Destination path for the exported OSI YAML file.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print the planned export without touching Neo4j.",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Emit JSON on stdout. Also accepted as a top-level flag.",
)
@click.pass_context
def osi_export(
    ctx: click.Context,
    *,
    semantic_model_name: str | None,
    output_path: str | None,
    dry_run: bool,
    json_flag: bool,
) -> None:
    """Export an OSI semantic model from Neo4j to an OSI YAML file.

    Reads the ``OsiSemanticModel`` with the given name (and everything it owns:
    tables, columns, metrics, joins, aspects) from the graph and writes it back
    out as an OSI YAML spec. The model name can come from the
    --semantic-model-name flag or the OSI_SEMANTIC_MODEL_NAME env var;
    --output-path is required. Pass --dry-run to print the planned export without
    touching Neo4j. If no model matches the name, the command exits with a
    not_found error (exit code 3).
    """
    settings = load_settings()
    semantic_model_name = require(
        "--semantic-model-name",
        resolve(semantic_model_name, settings.osi_semantic_model_name),
        env_var="OSI_SEMANTIC_MODEL_NAME",
    )
    output_path = require("--output-path", output_path)

    stdout = ctx.obj["stdout"]
    stderr = ctx.obj["stderr"]
    as_json = ctx.obj["as_json"] or json_flag

    if dry_run:
        payload = {
            "osi_export": {
                "dry_run": True,
                "semantic_model_name": semantic_model_name,
                "output_path": output_path,
                "database": settings.neo4j_database,
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

    with _neo4j_driver(settings) as driver:
        try:
            connector = OsiConnector(
                neo4j_driver=driver,
                database_name=settings.neo4j_database,
            )
            with cli_status(stderr, "Exporting OSI semantic model..."):
                connector.export(
                    semantic_model_name=semantic_model_name,
                    output_path=output_path,
                )
        except NeocartaError as exc:
            raise cli_error_from(exc) from exc
        except ValueError as exc:
            # OsiConnector.export raises a plain ValueError when no
            # OsiSemanticModel matches the name; surface it as a clean not_found
            # (exit 3) rather than an unhandled traceback (exit 1).
            raise CLIError(
                "not_found",
                str(exc),
                suggestion="Verify the --semantic-model-name exists in the graph.",
            ) from exc

    payload = {
        "osi_export": {
            "semantic_model_name": semantic_model_name,
            "output_path": output_path,
            "database": settings.neo4j_database,
            "status": "succeeded",
        }
    }
    if as_json:
        emit_json(payload)
    else:
        stdout.print(
            f"Exported OSI semantic model [bold]{semantic_model_name}[/bold] "
            f"from [bold]{settings.neo4j_database}[/bold] to [bold]{output_path}[/bold]."
        )
