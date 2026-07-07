"""``neocarta tool ...`` commands — the MCP server tools, mirrored on the CLI.

Each subcommand mirrors one tool exposed by the Neocarta MCP server
(:mod:`neocarta._mcp.tools`) by name, arguments, and documentation, and runs
the *same* Cypher against the *same* Neo4j semantic graph the server would. The
command names are the kebab-cased tool names (e.g. the ``list_schemas`` tool is
``neocarta tool list-schemas``), so an agent that knows the MCP surface already
knows the CLI surface. The group is named ``tool`` rather than ``mcp`` because
no MCP server is involved — these run directly against the CLI's Neo4j driver.

Unlike the MCP server — which builds an async FastMCP server and registers one
search tool per label based on the indexes present — these commands run
synchronously against the CLI's existing sync Neo4j driver, reusing the shared
Cypher builders (:mod:`neocarta._mcp.cypher`), result models
(:mod:`neocarta._mcp.models`), Lucene sanitiser (:mod:`neocarta._mcp.utils`),
and the same ``LiteLLMEmbeddingsConnector`` the ingest commands use. They need
only the ``[cli]`` install (no ``fastmcp``); the search tools additionally need
the matching vector / full-text indexes (created by an ingest with
``--embeddings``) and embedding-provider credentials.

The command docstrings below are copied verbatim from the corresponding MCP
tool functions in :mod:`neocarta._mcp.tools` so the documentation stays
mirrored; keep them in sync if a tool's docstring changes.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

import click

from ...errors import NeocartaError
from ..config import load_settings, require
from ..errors import CLIError, cli_error_from
from ..output import cli_status, emit_json
from ._common import _build_embedder, _neo4j_driver, _require_neo4j_settings

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from neo4j import Driver

    from ..config import CLISettings


@click.group()
def tool() -> None:
    """Query the Neo4j semantic graph with the MCP server's tools, from the CLI.

    Each subcommand mirrors one tool of the `neocarta-mcp` server by name,
    arguments, and documentation, querying the same Neo4j semantic graph — but
    runs directly against the CLI's Neo4j driver, with no MCP server involved. The
    catalog tools (list-schemas, list-tables-by-schema, get-full-metadata-schema)
    work from schema alone; the search tools require the matching vector /
    full-text indexes (built by an ingest with --embeddings) and, where they
    embed the query, embedding-provider credentials (e.g. OPENAI_API_KEY). The
    embedding model is read from EMBEDDING_MODEL / EMBEDDING_DIMENSIONS, just
    like the MCP server, so query and stored vectors agree.
    """


# --------------------------------------------------------------------------- #
# Shared plumbing
# --------------------------------------------------------------------------- #
def _json_option(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Attach the standard per-command ``--json`` flag (OR'd with the top-level one)."""
    return click.option(
        "--json",
        "json_flag",
        is_flag=True,
        default=False,
        help="Emit JSON on stdout. Also accepted as a top-level flag.",
    )(fn)


def _search_options(
    *,
    text_help: str,
    max_tables_default: int,
    max_tables_help: str,
    search_top_k_default: int,
    search_top_k_help: str,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Attach the shared ``--text-content`` / ``--max-tables`` / ``--search-top-k`` / ``--json``
    options, mirroring a search tool's ``text_content`` / ``max_tables`` / ``search_top_k``
    signature. Per-tool defaults and help text are passed in so each command documents
    exactly what its MCP tool documents.
    """

    def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn = _json_option(fn)
        fn = click.option(
            "--search-top-k",
            type=int,
            default=search_top_k_default,
            show_default=True,
            help=search_top_k_help,
        )(fn)
        fn = click.option(
            "--max-tables",
            type=int,
            default=max_tables_default,
            show_default=True,
            help=max_tables_help,
        )(fn)
        return click.option("--text-content", default=None, help=text_help)(fn)

    return wrap


def _cypher(tool: str) -> str:
    """Return the Cypher for ``tool`` from the shared builders.

    The builder for every tool is ``<tool>_cypher`` in :mod:`neocarta._mcp.cypher`,
    so the CLI and the MCP server always run identical queries.
    """
    # Lazy import keeps `neocarta --help` / `agent-context` free of the _mcp deps.
    from ..._mcp import cypher  # noqa: PLC0415

    return getattr(cypher, f"{tool}_cypher")()


def _map_neo4j_error(exc: Exception) -> CLIError:
    """Map a raw neo4j driver/server error to the CLI's structured error contract."""
    from neo4j.exceptions import AuthError  # noqa: PLC0415

    if isinstance(exc, AuthError):
        return CLIError(
            "auth_error",
            "Neo4j authentication failed.",
            suggestion="Check NEO4J_USERNAME and NEO4J_PASSWORD.",
        )
    message = str(exc).lower()
    if "no such" in message and "index" in message:
        return CLIError(
            "not_found",
            "A search index required by this tool does not exist in the graph.",
            suggestion=(
                "Run an ingest with --embeddings to build the vector and full-text "
                "indexes the search tools query, then retry."
            ),
        )
    return CLIError(
        "upstream_error",
        f"Neo4j query failed ({type(exc).__name__}).",
        suggestion="Check NEO4J_URI and that the Neo4j database is reachable.",
    )


@contextlib.contextmanager
def _read_driver(settings: CLISettings) -> Iterator[Driver]:
    """Yield a read-only Neo4j driver, translating library and driver errors to ``CLIError``.

    Validates Neo4j credentials first (raising ``usage_error`` if missing), then
    yields the sync driver. Any :class:`NeocartaError` is forwarded through
    :func:`cli_error_from`; any raw ``neo4j`` error is mapped by
    :func:`_map_neo4j_error`. A :class:`CLIError` raised inside the ``with`` body
    (e.g. an embedding failure) propagates unchanged.
    """
    from neo4j.exceptions import DriverError, Neo4jError  # noqa: PLC0415

    _require_neo4j_settings(settings)
    try:
        with _neo4j_driver(settings) as driver:
            yield driver
    except NeocartaError as exc:
        raise cli_error_from(exc) from exc
    except (Neo4jError, DriverError) as exc:
        raise _map_neo4j_error(exc) from exc


def _read_query(driver: Driver, settings: CLISettings, cypher: str, params: dict[str, Any]) -> list:
    """Run one read query and return ``record.data()`` rows."""
    from neo4j import RoutingControl  # noqa: PLC0415

    return driver.execute_query(
        query_=cypher,
        parameters_=params,
        database_=settings.neo4j_database,
        routing_=RoutingControl.READ,
        result_transformer_=lambda result: result.data(),
    )


def _embed_query(settings: CLISettings, driver: Driver, text_content: str) -> list[float]:
    """Embed ``text_content`` with the configured model, raising a clean error on failure.

    ``_create_embedding_sync`` swallows provider failures and returns ``None``
    (it logs only the exception type, never the text), so guard it here and turn
    a missing/invalid key or unknown model into a structured ``upstream_error``.
    """
    embedder = _build_embedder(settings, driver)
    embedding = embedder._create_embedding_sync(text_content)
    if embedding is None:
        raise CLIError(
            "upstream_error",
            "Failed to embed the query text.",
            suggestion=(
                "Check the embedding provider credentials (e.g. set OPENAI_API_KEY for "
                "OpenAI models, GEMINI_API_KEY for Gemini) and that EMBEDDING_MODEL "
                "matches the model the graph was embedded with."
            ),
        )
    return embedding


def _emit(ctx: click.Context, *, tool: str, json_flag: bool, body: dict[str, Any]) -> None:
    """Emit the result under the ``tool_<tool>`` envelope key (JSON or Rich)."""
    payload = {f"tool_{tool}": body}
    if ctx.obj["as_json"] or json_flag:
        emit_json(payload)
    else:
        ctx.obj["stdout"].print(payload)


def _table_contexts(rows: list) -> list[dict[str, Any]]:
    """Validate ``{"result": ...}`` rows into ``TableContext`` JSON dicts.

    A row returned in an unexpected shape (missing ``result`` key or a field that
    fails validation) is turned into a structured ``upstream_error`` rather than
    leaking a raw ``pydantic`` traceback as a generic exit 1.
    """
    from pydantic import ValidationError  # noqa: PLC0415

    from ..._mcp.models import TableContext  # noqa: PLC0415

    try:
        return [TableContext.model_validate(row["result"]).model_dump(mode="json") for row in rows]
    except (ValidationError, KeyError, TypeError) as exc:
        raise CLIError(
            "upstream_error",
            "The graph returned a row that did not match the expected table-context shape.",
            suggestion="Ensure the graph was loaded by a compatible neocarta version.",
        ) from exc


def _run_search(
    ctx: click.Context,
    *,
    tool: str,
    json_flag: bool,
    text_content: str | None,
    max_tables: int,
    search_top_k: int,
    embed: bool,
    lucene: bool,
) -> None:
    """Shared embed → cypher → emit flow for the nine search tools.

    ``embed`` controls whether the query is embedded (vector / hybrid tools) and
    ``lucene`` whether the sanitised text is passed as ``queryText`` (full-text /
    hybrid tools), matching each tool's parameter set.
    """
    from ..._mcp.utils import escape_lucene_query  # noqa: PLC0415

    text_content = require("--text-content", text_content)
    settings = load_settings()
    stderr = ctx.obj["stderr"]
    params: dict[str, Any] = {"searchTopK": search_top_k, "maxTables": max_tables}
    with _read_driver(settings) as driver:
        if embed:
            with cli_status(stderr, "Embedding query text..."):
                params["queryEmbedding"] = _embed_query(settings, driver, text_content)
        if lucene:
            query_text = escape_lucene_query(text_content)
            if not query_text:
                raise CLIError(
                    "usage_error",
                    "The query contained only Lucene special characters; nothing left to search.",
                    suggestion="Provide alphanumeric search terms in --text-content.",
                )
            params["queryText"] = query_text
        with cli_status(stderr, f"Running tool {tool}..."):
            rows = _read_query(driver, settings, _cypher(tool), params)
    body = {
        "tool": tool,
        "text_content": text_content,
        "max_tables": max_tables,
        "search_top_k": search_top_k,
        "results": _table_contexts(rows),
    }
    body["count"] = len(body["results"])
    _emit(ctx, tool=tool, json_flag=json_flag, body=body)


def _run_catalog(
    ctx: click.Context,
    *,
    tool: str,
    json_flag: bool,
    params: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    as_table_context: bool = False,
    count_field: str | None = None,
) -> None:
    """Shared cypher → emit flow for the three always-available catalog tools.

    ``count`` is the number of result objects, except when ``count_field`` is
    given: ``list_tables_by_schema`` aggregates every table into a single row
    (``collect(t.name)``), so its count is taken from that list's length instead.
    """
    settings = load_settings()
    stderr = ctx.obj["stderr"]
    with _read_driver(settings) as driver, cli_status(stderr, f"Running tool {tool}..."):
        rows = _read_query(driver, settings, _cypher(tool), params or {})
    results = _table_contexts(rows) if as_table_context else rows
    count = sum(len(row.get(count_field) or []) for row in rows) if count_field else len(results)
    body = {"tool": tool, **(extra or {}), "count": count, "results": results}
    _emit(ctx, tool=tool, json_flag=json_flag, body=body)


# --------------------------------------------------------------------------- #
# Catalog tools (always available)
# --------------------------------------------------------------------------- #
@tool.command("list-schemas")
@_json_option
@click.pass_context
def list_schemas(ctx: click.Context, *, json_flag: bool) -> None:
    """List all schemas and their databases.

    Use this as the first step when exploring an unfamiliar database or when
    you need a valid schema name to pass to other tools. Returns every schema
    alongside the database it belongs to.
    """
    _run_catalog(ctx, tool="list_schemas", json_flag=json_flag)


@tool.command("list-tables-by-schema")
@click.option(
    "--schema-name",
    default=None,
    help="The name of the schema to list tables for. Use `neocarta tool list-schemas` to get "
    "valid schema names.",
)
@_json_option
@click.pass_context
def list_tables_by_schema(ctx: click.Context, *, schema_name: str | None, json_flag: bool) -> None:
    """List all tables for a given schema.

    Use this when you already know the schema name and want to enumerate its
    tables. Call list_schemas first to obtain valid schema names.

    Parameters
    ----------
    schema_name: str
        The name of the schema to list tables for. Use list_schemas to get
        valid schema names.
    """
    schema_name = require("--schema-name", schema_name)
    _run_catalog(
        ctx,
        tool="list_tables_by_schema",
        json_flag=json_flag,
        params={"schemaName": schema_name},
        extra={"schema_name": schema_name},
        count_field="table_names",
    )


@tool.command("get-full-metadata-schema")
@_json_option
@click.pass_context
def get_full_metadata_schema(ctx: click.Context, *, json_flag: bool) -> None:
    """Return the complete metadata schema for every table in the database.

    WARNING: This fetches all tables and all columns without any filtering.
    On databases with many tables this will return a very large payload and
    should only be used for debugging or on small databases. Prefer the
    targeted retrieval tools for normal lookups.
    """
    _run_catalog(ctx, tool="get_full_metadata_schema", json_flag=json_flag, as_table_context=True)


# --------------------------------------------------------------------------- #
# Vector search tools
# --------------------------------------------------------------------------- #
@tool.command("get-context-by-column-vector-search")
@_search_options(
    text_help="Natural-language description or query to search for semantically similar columns.",
    max_tables_default=5,
    max_tables_help="Maximum number of tables in the returned context.",
    search_top_k_default=10,
    search_top_k_help="Number of column candidates the vector index returns before being grouped "
    "to parent tables. Increase to widen recall; decrease to tighten precision.",
)
@click.pass_context
def get_context_by_column_vector_search(
    ctx: click.Context,
    *,
    text_content: str | None,
    max_tables: int,
    search_top_k: int,
    json_flag: bool,
) -> None:
    """Find tables whose columns are semantically similar to the provided text.

    Anchors on the closest matching columns by embedding similarity, then
    groups those anchors by parent table and returns each table along with
    the matched columns only (their data types, example values, and
    foreign-key references). Unmatched columns of the same table are not
    included. Tables are ranked by the average anchor score across their
    matching columns.

    Prefer this tool when the query references specific field or column names
    (e.g. "customer email", "order total").

    Parameters
    ----------
    text_content: str
        Natural-language description or query to search for semantically
        similar columns.
    max_tables: int
        Maximum number of tables in the returned context.
    search_top_k: int
        Number of column candidates the vector index returns before being
        grouped to parent tables. Increase to widen recall; decrease to tighten precision.
    """
    _run_search(
        ctx,
        tool="get_context_by_column_vector_search",
        json_flag=json_flag,
        text_content=text_content,
        max_tables=max_tables,
        search_top_k=search_top_k,
        embed=True,
        lucene=False,
    )


@tool.command("get-context-by-table-vector-search")
@_search_options(
    text_help="Natural-language description or query to search for semantically similar tables.",
    max_tables_default=10,
    max_tables_help="Maximum number of tables in the returned context.",
    search_top_k_default=10,
    search_top_k_help="Number of table candidates the vector index returns before ranking. "
    "Increase to widen recall; decrease to tighten precision.",
)
@click.pass_context
def get_context_by_table_vector_search(
    ctx: click.Context,
    *,
    text_content: str | None,
    max_tables: int,
    search_top_k: int,
    json_flag: bool,
) -> None:
    """Find tables that are semantically similar to the provided text.

    Anchors on the closest matching tables by embedding similarity, then
    expands each anchor with its full set of columns (types, example values,
    foreign-key references) and its schema and database to return the full
    table context per hit. Ranked by table similarity.

    Prefer this tool when the query describes a general concept or entity
    (e.g. "customers", "sales transactions").

    Parameters
    ----------
    text_content: str
        Natural-language description or query to search for semantically
        similar tables.
    max_tables: int
        Maximum number of tables in the returned context.
    search_top_k: int
        Number of table candidates the vector index returns before ranking.
        Increase to widen recall; decrease to tighten precision.
    """
    _run_search(
        ctx,
        tool="get_context_by_table_vector_search",
        json_flag=json_flag,
        text_content=text_content,
        max_tables=max_tables,
        search_top_k=search_top_k,
        embed=True,
        lucene=False,
    )


@tool.command("get-context-by-schema-and-table-vector-search")
@_search_options(
    text_help="Natural-language description or query to search for semantically similar schemas "
    "and tables.",
    max_tables_default=5,
    max_tables_help="Maximum number of tables in the returned context.",
    search_top_k_default=5,
    search_top_k_help="Number of schema candidates the vector index returns before tables within "
    "those schemas are scored in-line. Increase to consider more schemas; decrease to tighten "
    "precision.",
)
@click.pass_context
def get_context_by_schema_and_table_vector_search(
    ctx: click.Context,
    *,
    text_content: str | None,
    max_tables: int,
    search_top_k: int,
    json_flag: bool,
) -> None:
    """Find tables by matching both schema and table embeddings to the provided text.

    Anchors first on the closest matching schemas, then narrows to tables
    within those schemas whose embeddings score near or better than the
    schema. Each surviving table is expanded with its full set of columns
    (types, example values, foreign-key references) and its database to
    return the full table context per hit. Ranked by schema score then table
    score.

    Prefer this tool when the query is broad and may span multiple schemas
    (e.g. "everything related to billing").

    Parameters
    ----------
    text_content: str
        Natural-language description or query to search for semantically
        similar schemas and tables.
    max_tables: int
        Maximum number of tables in the returned context.
    search_top_k: int
        Number of schema candidates the vector index returns before tables
        within those schemas are scored in-line. Increase to consider more
        schemas; decrease to tighten precision.
    """
    _run_search(
        ctx,
        tool="get_context_by_schema_and_table_vector_search",
        json_flag=json_flag,
        text_content=text_content,
        max_tables=max_tables,
        search_top_k=search_top_k,
        embed=True,
        lucene=False,
    )


# --------------------------------------------------------------------------- #
# Full-text search tools
# --------------------------------------------------------------------------- #
@tool.command("get-context-by-table-full-text-search")
@_search_options(
    text_help="The full-text search expression. Supports Lucene query syntax.",
    max_tables_default=10,
    max_tables_help="Maximum number of tables in the returned context.",
    search_top_k_default=10,
    search_top_k_help="Number of table candidates the full-text index returns before ranking. "
    "Increase to widen recall; decrease to tighten precision.",
)
@click.pass_context
def get_context_by_table_full_text_search(
    ctx: click.Context,
    *,
    text_content: str | None,
    max_tables: int,
    search_top_k: int,
    json_flag: bool,
) -> None:
    """Find tables by full-text matching on table name and description.

    Anchors on the closest matching tables via a full-text search over table
    names and descriptions, then expands each anchor with its full set of
    columns (types, example values, foreign-key references) and its schema
    and database to return the full table context per hit. No embeddings
    required.

    Prefer this tool when the query contains literal table-name tokens or
    specific keywords likely to appear verbatim in table metadata (e.g.
    "orders", "fct_revenue").

    Parameters
    ----------
    text_content: str
        The full-text search expression. Supports Lucene query syntax.
    max_tables: int
        Maximum number of tables in the returned context.
    search_top_k: int
        Number of table candidates the full-text index returns before ranking.
        Increase to widen recall; decrease to tighten precision.
    """
    _run_search(
        ctx,
        tool="get_context_by_table_full_text_search",
        json_flag=json_flag,
        text_content=text_content,
        max_tables=max_tables,
        search_top_k=search_top_k,
        embed=False,
        lucene=True,
    )


@tool.command("get-context-by-column-full-text-search")
@_search_options(
    text_help="The full-text search expression. Supports Lucene query syntax.",
    max_tables_default=5,
    max_tables_help="Maximum number of tables in the returned context.",
    search_top_k_default=10,
    search_top_k_help="Number of column candidates the full-text index returns before being "
    "grouped to parent tables. Increase to widen recall; decrease to tighten precision.",
)
@click.pass_context
def get_context_by_column_full_text_search(
    ctx: click.Context,
    *,
    text_content: str | None,
    max_tables: int,
    search_top_k: int,
    json_flag: bool,
) -> None:
    """Find tables by full-text matching on column name and description.

    Anchors on the closest matching columns via a full-text search over
    column names and descriptions, then groups those anchors by parent table
    and returns each table along with the matched columns only (their data
    types, example values, and foreign-key references). Unmatched columns
    of the same table are not included. Tables are ranked by the average
    anchor score across their matching columns. No embeddings required.

    Prefer this tool when the query references specific column-name tokens
    (e.g. "customer_id", "total_amount").

    Parameters
    ----------
    text_content: str
        The full-text search expression. Supports Lucene query syntax.
    max_tables: int
        Maximum number of tables in the returned context.
    search_top_k: int
        Number of column candidates the full-text index returns before being
        grouped to parent tables. Increase to widen recall; decrease to tighten precision.
    """
    _run_search(
        ctx,
        tool="get_context_by_column_full_text_search",
        json_flag=json_flag,
        text_content=text_content,
        max_tables=max_tables,
        search_top_k=search_top_k,
        embed=False,
        lucene=True,
    )


# --------------------------------------------------------------------------- #
# Hybrid search tools (vector + full-text)
# --------------------------------------------------------------------------- #
@tool.command("get-context-by-table-hybrid-search")
@_search_options(
    text_help="Natural-language and/or keyword query. The same string is used for both the "
    "embedding lookup and the full-text search.",
    max_tables_default=5,
    max_tables_help="Maximum number of tables in the returned context.",
    search_top_k_default=10,
    search_top_k_help="Number of table candidates each search branch returns before ranking. "
    "Increase to widen recall; decrease to tighten precision.",
)
@click.pass_context
def get_context_by_table_hybrid_search(
    ctx: click.Context,
    *,
    text_content: str | None,
    max_tables: int,
    search_top_k: int,
    json_flag: bool,
) -> None:
    """Find tables via a hybrid vector + full-text search at the table level.

    Anchors on tables using two parallel signals — embedding similarity and
    full-text matching on table name/description — normalizes each signal and
    merges them per table by taking the stronger of the two. Each surviving
    anchor is then expanded with its full set of columns (types, example
    values, foreign-key references) and its schema and database to return the
    full table context per hit.

    Prefer this tool when the query mixes conceptual phrasing with literal
    tokens you expect to see verbatim in table metadata.

    Parameters
    ----------
    text_content: str
        Natural-language and/or keyword query. The same string is used for
        both the embedding lookup and the full-text search.
    max_tables: int
        Maximum number of tables in the returned context.
    search_top_k: int
        Number of table candidates each search branch returns before
        ranking. Increase to widen recall; decrease to tighten precision.
    """
    _run_search(
        ctx,
        tool="get_context_by_table_hybrid_search",
        json_flag=json_flag,
        text_content=text_content,
        max_tables=max_tables,
        search_top_k=search_top_k,
        embed=True,
        lucene=True,
    )


@tool.command("get-context-by-column-hybrid-search")
@_search_options(
    text_help="Natural-language and/or keyword query. The same string is used for both the "
    "embedding lookup and the full-text search.",
    max_tables_default=5,
    max_tables_help="Maximum number of tables in the returned context.",
    search_top_k_default=10,
    search_top_k_help="Number of column candidates each search branch returns before being "
    "grouped to parent tables. Increase to widen recall; decrease to tighten precision.",
)
@click.pass_context
def get_context_by_column_hybrid_search(
    ctx: click.Context,
    *,
    text_content: str | None,
    max_tables: int,
    search_top_k: int,
    json_flag: bool,
) -> None:
    """Find tables via a hybrid vector + full-text search at the column level.

    Anchors on columns using two parallel signals — embedding similarity and
    full-text matching on column name/description — normalizes each signal
    and merges them per column by taking the stronger of the two. Anchors
    are then grouped by parent table, and each table is returned along with
    the matched columns only (their data types, example values, and
    foreign-key references). Unmatched columns of the same table are not
    included. Tables are ranked by the average anchor score across their
    matching columns.

    Prefer this tool when the query references specific field-level concepts
    alongside literal token names.

    Parameters
    ----------
    text_content: str
        Natural-language and/or keyword query. The same string is used for
        both the embedding lookup and the full-text search.
    max_tables: int
        Maximum number of tables in the returned context.
    search_top_k: int
        Number of column candidates each search branch returns before being
        grouped to parent tables. Increase to widen recall; decrease to tighten precision.
    """
    _run_search(
        ctx,
        tool="get_context_by_column_hybrid_search",
        json_flag=json_flag,
        text_content=text_content,
        max_tables=max_tables,
        search_top_k=search_top_k,
        embed=True,
        lucene=True,
    )


# --------------------------------------------------------------------------- #
# Business-term-bridged hybrid search tools
# --------------------------------------------------------------------------- #
@tool.command("get-context-by-table-business-term-hybrid-search")
@_search_options(
    text_help="Natural-language and/or business-term query. The same string is used for the "
    "embedding lookup and both full-text branches.",
    max_tables_default=5,
    max_tables_help="Maximum number of tables in the returned context.",
    search_top_k_default=10,
    search_top_k_help="Number of candidates each search call returns — applies to the table "
    "vector lookup, the table full-text lookup, and the business-term full-text lookup. Increase "
    "to widen recall; decrease to tighten precision.",
)
@click.pass_context
def get_context_by_table_business_term_hybrid_search(
    ctx: click.Context,
    *,
    text_content: str | None,
    max_tables: int,
    search_top_k: int,
    json_flag: bool,
) -> None:
    """Find tables via vector + full-text search, with the full-text branch routed through business-glossary terms.

    Anchors on tables using two parallel signals:
    (1) embedding similarity on table descriptions, and
    (2) full-text matches on business-glossary terms — surfacing only those
    tables that are tagged to a matching glossary term AND whose name or
    description also matches the query.

    The two signals are normalized and merged per table by taking the stronger
    of the two. Each surviving anchor is then expanded with its full set of
    columns (types, example values, foreign-key references) and its schema and
    database to return the full table context per hit.

    Prefer this tool when the query uses business-glossary language (e.g.
    "average order value", "gross merchandise value") that may not appear
    verbatim in table metadata but is captured by glossary tags.

    Parameters
    ----------
    text_content: str
        Natural-language and/or business-term query. The same string is used
        for the embedding lookup and both full-text branches.
    max_tables: int
        Maximum number of tables in the returned context.
    search_top_k: int
        Number of candidates each search call returns — applies to the table
        vector lookup, the table full-text lookup, and the business-term
        full-text lookup. Increase to widen recall; decrease to tighten
        precision.
    """
    _run_search(
        ctx,
        tool="get_context_by_table_business_term_hybrid_search",
        json_flag=json_flag,
        text_content=text_content,
        max_tables=max_tables,
        search_top_k=search_top_k,
        embed=True,
        lucene=True,
    )


@tool.command("get-context-by-column-business-term-hybrid-search")
@_search_options(
    text_help="Natural-language and/or business-term query. The same string is used for the "
    "embedding lookup and both full-text branches.",
    max_tables_default=5,
    max_tables_help="Maximum number of tables in the returned context.",
    search_top_k_default=10,
    search_top_k_help="Number of candidates each search call returns — applies to the column "
    "vector lookup, the column full-text lookup, and the business-term full-text lookup. Increase "
    "to widen recall; decrease to tighten precision.",
)
@click.pass_context
def get_context_by_column_business_term_hybrid_search(
    ctx: click.Context,
    *,
    text_content: str | None,
    max_tables: int,
    search_top_k: int,
    json_flag: bool,
) -> None:
    """Find tables via vector + full-text search at the column level, with the full-text branch routed through business-glossary terms.

    Anchors on columns using two parallel signals:
    (1) embedding similarity on column descriptions, and
    (2) full-text matches on business-glossary terms — surfacing only those
    columns that are tagged to a matching glossary term AND whose name or
    description also matches the query.

    The two signals are normalized and merged per column by taking the
    stronger of the two. Anchors are then grouped by parent table, and each
    table is returned along with the matched columns only (their data types,
    example values, and foreign-key references). Unmatched columns of the
    same table are not included. Tables are ranked by the average anchor
    score across their matching columns.

    Prefer this tool when business-glossary language maps onto field-level
    concepts via column tags (e.g. "customer acquisition cost" tagged to a
    cost column).

    Parameters
    ----------
    text_content: str
        Natural-language and/or business-term query. The same string is used
        for the embedding lookup and both full-text branches.
    max_tables: int
        Maximum number of tables in the returned context.
    search_top_k: int
        Number of candidates each search call returns — applies to the column
        vector lookup, the column full-text lookup, and the business-term
        full-text lookup. Increase to widen recall; decrease to tighten precision.
    """
    _run_search(
        ctx,
        tool="get_context_by_column_business_term_hybrid_search",
        json_flag=json_flag,
        text_content=text_content,
        max_tables=max_tables,
        search_top_k=search_top_k,
        embed=True,
        lucene=True,
    )
