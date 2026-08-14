"""``neocarta memory ...`` commands — semantic-memory administration.

One verb is exposed:

* ``init-indexes`` — create the ``phrase_vector_index`` and
  ``phrase_full_text_index`` that back the MCP server's ``recall_task_memory``
  tool. Run once per graph before recall is used.

Memory is a graph feature independent of the MCP server runtime: index creation
needs only a Neo4j driver and an embedder (to discover the vector dimension), so
this lives in its own command group and requires only the ``cli`` extra — not
the ``mcp`` (fastmcp) extra that ``neocarta mcp serve`` needs, and unlike
``neocarta tool ...`` it writes to the graph rather than mirroring a read tool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from ...errors import NeocartaError
from ..config import load_settings
from ..errors import CLIError, cli_error_from
from ..output import cli_status, emit_json
from ._common import (
    _apply_neo4j_overrides,
    _build_embedder,
    _neo4j_driver,
    _require_neo4j_settings,
    neo4j_options,
)

if TYPE_CHECKING:
    from ...enrichment.embeddings import BaseEmbeddingsConnector


@click.group()
def memory() -> None:
    """Administer the Neo4j semantic-memory feature (Task/Phrase/Query graph)."""


@memory.command("init-indexes")
@click.option(
    "--embedding-model",
    default=None,
    help="Embedding model id in LiteLLM format (default: text-embedding-3-small). Must match the "
    "model the MCP server embeds phrasings with.",
)
@click.option(
    "--embedding-dimensions",
    type=int,
    default=None,
    help="Dimension to request from the embedding model (maps to EMBEDDING_DIMENSIONS). Optional "
    "— omit for the model's native size. The index is built at the size the model actually "
    "returns, so it must match the MCP server's EMBEDDING_DIMENSIONS or vector recall will error.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print what would be created without touching Neo4j.",
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
def memory_init_indexes(
    ctx: click.Context,
    *,
    embedding_model: str | None,
    embedding_dimensions: int | None,
    dry_run: bool,
    json_flag: bool,
    neo4j_uri: str | None,
    neo4j_username: str | None,
    neo4j_database: str | None,
) -> None:
    """Create the phrase vector + full-text indexes backing memory recall.

    The ``recall_task_memory`` MCP tool searches ``Phrase`` nodes over a
    ``phrase_vector_index`` (their embeddings) and a ``phrase_full_text_index``
    (their verbatim text). Capture writes those nodes regardless, but recall
    returns nothing until these indexes exist — run this once per graph. The
    vector index is built at the dimension the embedding model returns
    (EMBEDDING_MODEL / --embedding-model, and EMBEDDING_DIMENSIONS /
    --embedding-dimensions), probed via one embedding call, so it requires the
    provider credentials (e.g. OPENAI_API_KEY). These must match the MCP
    server's embedding config. Pass --dry-run to print the plan without touching
    Neo4j.
    """
    settings = load_settings()
    _apply_neo4j_overrides(
        settings,
        neo4j_uri=neo4j_uri,
        neo4j_username=neo4j_username,
        neo4j_database=neo4j_database,
    )
    if embedding_model is not None:
        settings.embedding_model = embedding_model
    if embedding_dimensions is not None:
        settings.embedding_dimensions = embedding_dimensions

    stdout = ctx.obj["stdout"]
    stderr = ctx.obj["stderr"]
    as_json = ctx.obj["as_json"] or json_flag

    if dry_run:
        payload = {
            "memory_init_indexes": {
                "dry_run": True,
                "database": settings.neo4j_database,
                "indexes": ["phrase_vector_index", "phrase_full_text_index"],
                "embedding_model": settings.embedding_model,
                "embedding_dimensions": settings.embedding_dimensions,
            }
        }
        if as_json:
            emit_json(payload)
        else:
            stdout.print(payload)
        return

    _require_neo4j_settings(settings)

    # Lazy import: keep the ingest DDL dependency off the --help / --dry-run path.
    from ...ingest.indexes import create_memory_indexes  # noqa: PLC0415

    with _neo4j_driver(settings) as driver:
        try:
            embedder = _build_embedder(settings, driver)
            with cli_status(stderr, "Probing embedding dimension..."):
                resolved_dimensions = _probe_dimensions(embedder)
            with cli_status(stderr, "Creating memory indexes..."):
                summaries = create_memory_indexes(
                    driver,
                    dimensions=resolved_dimensions,
                    database_name=settings.neo4j_database,
                )
        except NeocartaError as exc:
            raise cli_error_from(exc) from exc

    payload = {
        "memory_init_indexes": {
            "database": settings.neo4j_database,
            "dimensions": resolved_dimensions,
            "indexes": summaries,
            "status": "succeeded",
        }
    }
    if as_json:
        emit_json(payload)
    else:
        stdout.print(
            f"Created memory indexes (phrase_vector_index @ {resolved_dimensions} dims, "
            f"phrase_full_text_index) in [bold]{settings.neo4j_database}[/bold]."
        )


def _probe_dimensions(embedder: BaseEmbeddingsConnector) -> int:
    """Probe the embedder for its output dimension, wrapping provider failures.

    ``_probe_dimensions_sync`` makes a live embedding call and raises on missing
    or invalid credentials / model; normalise that into the CLI error contract
    so agents get a clean envelope instead of a raw traceback.
    """
    try:
        return embedder._probe_dimensions_sync()
    except Exception as exc:
        raise CLIError(
            "upstream_error",
            "Failed to probe the embedding dimension.",
            suggestion=(
                "Check the embedding provider credentials (e.g. set OPENAI_API_KEY for OpenAI "
                "models, GEMINI_API_KEY for Gemini) and that EMBEDDING_MODEL is valid, or pass "
                "--dimensions to skip the probe."
            ),
        ) from exc
