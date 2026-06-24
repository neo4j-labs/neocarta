"""``neocarta databricks ...`` commands.

One verb is exposed:

* ``tags`` — wraps :class:`neocarta.connectors.databricks.DatabricksTagsConnector`
  to load managed-Databricks Unity Catalog **governed-tag definitions** into the
  vendor-neutral governance-tag model (``GovernanceTagKey``,
  ``GovernanceTagValue``). Reads tag policies via the Databricks SDK — no SQL
  warehouse required.
"""

from __future__ import annotations

import click

from ...enums import NodeLabel
from ...errors import NeocartaError
from ..config import load_settings, require, require_secret, resolve
from ..errors import cli_error_from
from ..output import cli_status, emit_json
from ._common import _build_embedder, _neo4j_driver, _require_neo4j_settings, _run_embeddings

# Default platform/system tag-key prefixes excluded unless --include-system-tags.
# Mirrors neocarta.connectors.databricks.tags.extract.DEFAULT_SYSTEM_PREFIXES; kept
# as a literal here so the CLI does not import the connector (and its heavy deps)
# at module load just to render --help.
_DEFAULT_SYSTEM_PREFIXES = "system.,class.,ai.,sap."


@click.group()
def databricks() -> None:
    """Run Databricks connectors against managed Unity Catalog."""


@databricks.command("tags")
@click.option(
    "--host",
    default=None,
    help="Databricks workspace URL, e.g. https://dbc-xxxx.cloud.databricks.com. "
    "Overrides DATABRICKS_HOST.",
)
@click.option(
    "--include-system-tags/--no-include-system-tags",
    "include_system_tags",
    default=False,
    help="Also ingest platform-managed governed tags matching --system-prefixes "
    "(default: disabled).",
)
@click.option(
    "--system-prefixes",
    default=_DEFAULT_SYSTEM_PREFIXES,
    help="Comma-separated tag-key prefixes treated as platform/system tags and excluded "
    f"unless --include-system-tags is set (default: {_DEFAULT_SYSTEM_PREFIXES}). "
    "Pass an empty string to disable prefix-based filtering.",
)
@click.option(
    "--source",
    default=None,
    help="Explicit namespace for governance-tag node ids (default: derived from the metastore id).",
)
@click.option(
    "--embeddings/--no-embeddings",
    "embeddings",
    default=False,
    help="Generate embeddings for ingested GovernanceTagKey nodes after load (default: disabled).",
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
    help="Print the planned ingestion without touching Neo4j or Databricks.",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help="Emit JSON on stdout. Also accepted as a top-level flag.",
)
@click.pass_context
def databricks_tags(
    ctx: click.Context,
    *,
    host: str | None,
    include_system_tags: bool,
    system_prefixes: str,
    source: str | None,
    embeddings: bool,
    embedding_model: str | None,
    embedding_dimensions: int | None,
    embedding_batch_size: int | None,
    dry_run: bool,
    json_flag: bool,
) -> None:
    """Ingest Databricks governed-tag definitions into the Neo4j semantic graph.

    Reads governed-tag definitions (tag policies) via the Databricks SDK — no SQL
    warehouse required — and loads a GovernanceTagKey per tag key, a
    GovernanceTagValue per allowed value, and a HAS_VALUE_OPTION edge between them.
    Tag assignments (TAGGED_WITH edges to columns/tables) live in
    information_schema and are a planned follow-up. Platform/partner-managed tags
    (keys matching --system-prefixes, default system.,class.,ai.,sap.) are excluded
    unless --include-system-tags is set. When --embeddings is enabled,
    GovernanceTagKey description embeddings are generated via LiteLLM and written
    back. Pass --dry-run to print the planned ingestion without touching Neo4j or
    Databricks. The workspace URL comes from --host or DATABRICKS_HOST; the access
    token is read only from DATABRICKS_TOKEN (secret), never a flag.
    """
    settings = load_settings()
    host = require("--host", resolve(host, settings.databricks_host), env_var="DATABRICKS_HOST")
    # Parse the comma-separated prefixes into a tuple; an empty string disables filtering.
    prefixes = tuple(p.strip() for p in system_prefixes.split(",") if p.strip())
    if embedding_model is not None:
        settings.embedding_model = embedding_model
    if embedding_dimensions is not None:
        settings.embedding_dimensions = embedding_dimensions
    if embedding_batch_size is not None:
        settings.embedding_batch_size = embedding_batch_size

    stdout = ctx.obj["stdout"]
    stderr = ctx.obj["stderr"]
    as_json = ctx.obj["as_json"] or json_flag
    node_labels = [NodeLabel.GOVERNANCE_TAG_KEY]

    if dry_run:
        payload = {
            "databricks_tags": {
                "dry_run": True,
                "host": host,
                "include_system_tags": include_system_tags,
                "system_prefixes": list(prefixes),
                "source": source,
                "database": settings.neo4j_database,
                "embeddings": embeddings,
                "embedding_model": settings.embedding_model if embeddings else None,
                "embedding_dimensions": settings.embedding_dimensions if embeddings else None,
                "embedding_batch_size": settings.embedding_batch_size if embeddings else None,
                "node_labels": [label.value for label in node_labels] if embeddings else None,
            }
        }
        if as_json:
            emit_json(payload)
        else:
            stdout.print(payload)
        return

    _require_neo4j_settings(settings)
    token = require_secret(
        "DATABRICKS_TOKEN", settings.databricks_token, env_var="DATABRICKS_TOKEN"
    )

    # Lazy imports: the Databricks SDK / connector only load when the command runs.
    from databricks.sdk import WorkspaceClient  # noqa: PLC0415

    from ...connectors.databricks import DatabricksTagsConnector  # noqa: PLC0415

    connector_kwargs: dict[str, object] = {"system_prefixes": prefixes}
    if source is not None:
        connector_kwargs["source"] = source

    with _neo4j_driver(settings) as driver:
        try:
            connector = DatabricksTagsConnector(
                # Unwrap the secret inline so the raw token never lives in a named local.
                workspace_client=WorkspaceClient(host=host, token=token.get_secret_value()),
                neo4j_driver=driver,
                database_name=settings.neo4j_database,
                **connector_kwargs,
            )
            with cli_status(stderr, "Ingesting Databricks governed-tag metadata..."):
                connector.ingest(include_system_tags=include_system_tags)

            if embeddings:
                embedder = _build_embedder(settings, driver)
                with cli_status(stderr, "Generating embeddings..."):
                    _run_embeddings(embedder, node_labels, batch_size=settings.embedding_batch_size)
        except NeocartaError as exc:
            raise cli_error_from(exc) from exc

    payload = {
        "databricks_tags": {
            "host": host,
            "database": settings.neo4j_database,
            "include_system_tags": include_system_tags,
            "embeddings": embeddings,
            "status": "succeeded",
        }
    }
    if as_json:
        emit_json(payload)
    else:
        stdout.print(
            f"Ingested Databricks governed tags from [bold]{host}[/bold] into "
            f"[bold]{settings.neo4j_database}[/bold] "
            f"({'with' if embeddings else 'without'} embeddings)."
        )
