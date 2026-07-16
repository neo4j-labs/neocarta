"""``neocarta query-log ...`` commands.

One verb is exposed:

* ``ingest`` — wraps :class:`neocarta.connectors.query_log.QueryLogConnector`,
  parsing a local query-log JSON file and loading the queries (plus the tables
  and columns they reference) into the Neo4j semantic graph.

This is distinct from ``neocarta bigquery logs``, which pulls query logs live
from the BigQuery Cloud Logging API; this command reads a file already on disk.
"""

from __future__ import annotations

from pathlib import Path

import click

from ...errors import NeocartaError
from ..config import load_settings, require, resolve
from ..errors import CLIError, cli_error_from
from ..output import cli_status, emit_json
from ._common import _apply_neo4j_overrides, _neo4j_driver, _require_neo4j_settings, neo4j_options


@click.group("query-log")
def query_log() -> None:
    """Run the query-log connector against a local query-log file."""


@query_log.command("ingest")
@click.option(
    "--query-log-file",
    default=None,
    help="Path to the query-log JSON file. Overrides QUERY_LOG_FILE.",
)
@click.option(
    "--source",
    default="bigquery",
    help="Source/format of the query-log file (default: bigquery).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print the planned ingestion without reading the file or touching Neo4j.",
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
def query_log_ingest(
    ctx: click.Context,
    *,
    query_log_file: str | None,
    source: str,
    dry_run: bool,
    json_flag: bool,
    neo4j_uri: str | None,
    neo4j_username: str | None,
    neo4j_database: str | None,
) -> None:
    """Parse a local query-log file into the Neo4j semantic graph.

    Reads a query-log JSON file (currently the ``bigquery`` export format) and
    loads Query and CTE nodes plus the Database/Schema/Table/Column structure and
    the table/column references each query touches. The file path comes from the
    --query-log-file flag or the QUERY_LOG_FILE env var. Pass --dry-run to print
    the planned ingestion without reading the file or touching Neo4j. No
    embeddings are generated: query-log nodes carry no descriptions to embed.
    """
    settings = load_settings()
    _apply_neo4j_overrides(
        settings,
        neo4j_uri=neo4j_uri,
        neo4j_username=neo4j_username,
        neo4j_database=neo4j_database,
    )
    query_log_file = require(
        "--query-log-file",
        resolve(query_log_file, settings.query_log_file),
        env_var="QUERY_LOG_FILE",
    )

    stdout = ctx.obj["stdout"]
    stderr = ctx.obj["stderr"]
    as_json = ctx.obj["as_json"] or json_flag

    if dry_run:
        payload = {
            "query_log_ingest": {
                "dry_run": True,
                "query_log_file": query_log_file,
                "source": source,
                "database": settings.neo4j_database,
            }
        }
        if as_json:
            emit_json(payload)
        else:
            stdout.print(payload)
        return

    # The connector opens the file with a bare ``Path(...).open()``, which raises
    # a plain FileNotFoundError rather than a NeocartaError (so it would escape
    # the adapter below). Catch the common missing-file case here and map it to
    # the not_found exit code.
    if not Path(query_log_file).is_file():
        raise CLIError(
            "not_found",
            f"Query log file not found: {query_log_file}.",
            suggestion="Check the path passed to --query-log-file or QUERY_LOG_FILE.",
        )

    _require_neo4j_settings(settings)

    # Lazy import: keep the connector dependency off the --help / --dry-run path.
    from ...connectors.query_log import QueryLogConnector  # noqa: PLC0415

    with _neo4j_driver(settings) as driver:
        try:
            connector = QueryLogConnector(
                neo4j_driver=driver,
                database_name=settings.neo4j_database,
            )
            with cli_status(stderr, "Ingesting query log..."):
                connector.ingest(query_log_file=query_log_file, source=source)
        except NeocartaError as exc:
            raise cli_error_from(exc) from exc

        extractor = connector.extractor
        result = {
            "query_log_file": query_log_file,
            "source": source,
            "database": settings.neo4j_database,
            "queries": len(extractor.query_info),
            "tables_referenced": len(extractor.table_info),
            "columns_referenced": len(extractor.column_info),
            "status": "succeeded",
        }

    payload = {"query_log_ingest": result}
    if as_json:
        emit_json(payload)
    else:
        stdout.print(
            f"Loaded {result['queries']} queries referencing "
            f"{result['tables_referenced']} tables / {result['columns_referenced']} columns "
            f"from [bold]{query_log_file}[/bold] into [bold]{settings.neo4j_database}[/bold]."
        )
