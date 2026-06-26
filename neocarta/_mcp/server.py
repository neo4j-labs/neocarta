"""FastMCP server exposing semantic layer metadata tools."""

import asyncio
import os
import logging
from collections.abc import Callable

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.utilities.logging import get_logger
from neo4j import AsyncDriver, AsyncGraphDatabase

from .. import __version__
from ..enrichment.embeddings import LiteLLMEmbeddingsConnector
from .embeddings import create_embedder
from .inventory import (
    fetch_index_inventory,
    fetch_neocarta_graph_metadata,
    has_business_term_nodes,
    has_osi_nodes,
)
from .settings import mcp_server_settings
from .tools import (
    catalog,
    full_text_search,
    hybrid_business_term_search,
    hybrid_search,
    osi_catalog,
    osi_definitions,
    osi_domain,
    vector_search,
)

logger = get_logger("neocarta")

RegisterFn = Callable[[FastMCP, AsyncDriver, str, LiteLLMEmbeddingsConnector], None]


def _select_search_strategy(
    label: str,
    inventory: set[tuple[str, str]],
    business_term_search_available: bool,
) -> str | None:
    """
    Decide which retrieval strategy to register for ``label``.

    Priority (highest to lowest): business-term-bridged hybrid > hybrid > vector or full-text.
    The business-term-bridged strategy also requires ``business_term_search_available``,
    which combines BusinessTerm full-text index presence with the existence of BusinessTerm
    nodes in the database.
    """
    has_vector = (label, "VECTOR") in inventory
    has_full_text = (label, "FULLTEXT") in inventory

    if has_vector and has_full_text and business_term_search_available:
        return "business_term_hybrid"
    if has_vector and has_full_text:
        return "hybrid"
    if has_vector:
        return "vector"
    if has_full_text:
        return "full_text"
    return None


def _register_for_label(
    server: FastMCP,
    neo4j_driver: AsyncDriver,
    neo4j_database: str,
    embedder: LiteLLMEmbeddingsConnector,
    strategy: str,
    registrars: dict[str, RegisterFn],
) -> None:
    """Dispatch the chosen strategy to its per-label registrar."""
    registrar = registrars.get(strategy)
    if registrar is None:
        return
    registrar(server, neo4j_driver, neo4j_database, embedder)


async def _validate_graph_version(neo4j_driver: AsyncDriver, neo4j_database: str) -> None:
    """
    Warn if the graph's recorded neocarta version differs from this server's.

    The ``__neocarta_graph__`` node is written by connectors on each run and
    records the neocarta version responsible. A mismatch usually means the
    MCP server and the connector that loaded the graph were installed from
    different package versions and may disagree on schema details.
    """
    metadata = await fetch_neocarta_graph_metadata(neo4j_driver, neo4j_database)
    if metadata is None:
        logger.warning(
            "No `__neocarta_graph__` metadata node found in database %r. "
            "The graph may have been loaded by a neocarta version that pre-dates "
            "graph metadata, or by a non-neocarta process.",
            neo4j_database,
        )
        return
    if metadata.latest_version != __version__:
        logger.warning(
            "Neocarta version mismatch: MCP server is running %s but the graph "
            "was last written by %s (initial version %s). Behavior may be "
            "unexpected — align the connector and MCP server versions.",
            __version__,
            metadata.latest_version,
            metadata.initial_version,
        )
    else:
        logger.info(
            "Neocarta graph metadata version %s matches MCP server version.",
            metadata.latest_version,
        )


async def create_mcp_server(
    neo4j_driver: AsyncDriver,
    neo4j_database: str,
    embedder: LiteLLMEmbeddingsConnector,
) -> FastMCP:
    """
    Create and configure the FastMCP server with all semantic-layer tools.

    At startup the target database is probed for its node-scoped search indexes and the
    presence of BusinessTerm and OSI nodes. For each searchable label (Table, Column,
    Metric) the single highest-priority retrieval tool whose prerequisites are satisfied is
    registered: business-term-bridged hybrid, then plain hybrid, then vector or full-text.
    Schema-level vector retrieval is registered independently.

    Catalog tools (schema/table listing, full metadata dump) are always registered. When an
    OSI semantic model is present, the OSI reference (list_domains,
    list_metrics_by_domain), domain-context (get_domain_context), and definition
    (get_metric_expression) tools are registered as well.
    """
    name = "Neocarta MCP Server"
    instructions = """
This is an MCP server that facilitates context retrieval from a Neo4j semantic layer.
The retrieved context may be used for query generation, query routing or data discovery.
"""
    server = FastMCP(name=name, instructions=instructions)

    await _validate_graph_version(neo4j_driver, neo4j_database)

    inventory = await fetch_index_inventory(neo4j_driver, neo4j_database)
    business_term_index_present = ("BusinessTerm", "FULLTEXT") in inventory
    business_term_nodes_present = await has_business_term_nodes(neo4j_driver, neo4j_database)
    business_term_search_available = business_term_index_present and business_term_nodes_present
    osi_nodes_present = await has_osi_nodes(neo4j_driver, neo4j_database)

    logger.info(
        "Detected search indexes: %s",
        sorted(inventory) if inventory else "(none)",
    )
    logger.info(
        "BusinessTerm full-text index present=%s, BusinessTerm nodes present=%s",
        business_term_index_present,
        business_term_nodes_present,
    )
    logger.info("OSI semantic model nodes present=%s", osi_nodes_present)

    catalog.register(server, neo4j_driver, neo4j_database)

    if osi_nodes_present:
        osi_catalog.register(server, neo4j_driver, neo4j_database)
        osi_domain.register(server, neo4j_driver, neo4j_database)
        osi_definitions.register(server, neo4j_driver, neo4j_database)
        logger.info("Registered OSI catalog, domain-context, and definition tools")

    if ("Schema", "VECTOR") in inventory:
        vector_search.register_schema_tool(server, neo4j_driver, neo4j_database, embedder)
        logger.info("Registered schema vector tool")

    per_label_registrars: dict[str, dict[str, RegisterFn]] = {
        "Table": {
            "business_term_hybrid": hybrid_business_term_search.register_table_tool,
            "hybrid": hybrid_search.register_table_tool,
            "vector": vector_search.register_table_tool,
            "full_text": full_text_search.register_table_tool,
        },
        "Column": {
            "business_term_hybrid": hybrid_business_term_search.register_column_tool,
            "hybrid": hybrid_search.register_column_tool,
            "vector": vector_search.register_column_tool,
            "full_text": full_text_search.register_column_tool,
        },
        "Metric": {
            "business_term_hybrid": hybrid_business_term_search.register_metric_tool,
            "hybrid": hybrid_search.register_metric_tool,
            "vector": vector_search.register_metric_tool,
            "full_text": full_text_search.register_metric_tool,
        },
    }

    for label, registrars in per_label_registrars.items():
        strategy = _select_search_strategy(label, inventory, business_term_search_available)
        if strategy is None:
            logger.info("No search index for %s; no tool registered", label)
            continue
        _register_for_label(server, neo4j_driver, neo4j_database, embedder, strategy, registrars)
        logger.info("Registered %s tool for %s", strategy, label)

    return server


async def main() -> None:
    """Initialize drivers, create the MCP server, and run it over stdio."""
    neo4j_driver = AsyncGraphDatabase.driver(
        uri=mcp_server_settings.neo4j_uri,
        auth=(mcp_server_settings.neo4j_username, mcp_server_settings.neo4j_password),
    )
    neo4j_database = mcp_server_settings.neo4j_database
    embedder = create_embedder(
        neo4j_driver=neo4j_driver,
        database_name=neo4j_database,
    )
    server = await create_mcp_server(neo4j_driver, neo4j_database, embedder)

    await server.run_stdio_async()


def run() -> None:
    """Load environment variables and run the MCP server."""
    load_dotenv()
    debug = os.getenv("NEOCARTA_DEBUG", "").lower() in ("1", "true")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logging.getLogger("fastmcp").setLevel(logging.DEBUG if debug else logging.WARNING)
    asyncio.run(main())


if __name__ == "__main__":
    run()
