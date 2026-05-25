"""Full-text-search-based MCP tools, registered per label."""

from fastmcp import FastMCP
from neo4j import AsyncDriver, RoutingControl

from ...enrichment.embeddings import LiteLLMEmbeddingsConnector
from ..cypher import (
    get_context_by_column_full_text_search_cypher,
    get_context_by_table_full_text_search_cypher,
)
from ..models import TableContext
from ..utils import remove_lucene_chars


def register_table_tool(
    server: FastMCP,
    neo4j_driver: AsyncDriver,
    neo4j_database: str,
    embedder: LiteLLMEmbeddingsConnector,
) -> None:
    """Register the table-level full-text search tool.

    ``embedder`` is unused here but accepted to keep a unified registrar signature
    across all tool modules so :mod:`neocarta._mcp.server` can dispatch uniformly.
    """

    @server.tool()
    async def get_context_by_table_full_text_search(
        text_content: str,
        max_tables: int = 10,
        search_top_k: int = 10,
    ) -> list[TableContext]:
        """
        Find tables by full-text matching on table name and description.

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
        cypher = get_context_by_table_full_text_search_cypher()
        results = await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={
                "queryText": remove_lucene_chars(text_content),
                "searchTopK": search_top_k,
                "maxTables": max_tables,
            },
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )
        return [TableContext.model_validate(r["result"]) for r in results]


def register_column_tool(
    server: FastMCP,
    neo4j_driver: AsyncDriver,
    neo4j_database: str,
    embedder: LiteLLMEmbeddingsConnector,
) -> None:
    """Register the column-level full-text search tool.

    ``embedder`` is unused here but accepted to keep a unified registrar signature
    across all tool modules so :mod:`neocarta._mcp.server` can dispatch uniformly.
    """

    @server.tool()
    async def get_context_by_column_full_text_search(
        text_content: str,
        max_tables: int = 5,
        search_top_k: int = 10,
    ) -> list[TableContext]:
        """
        Find tables by full-text matching on column name and description.

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
        cypher = get_context_by_column_full_text_search_cypher()
        results = await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={
                "queryText": remove_lucene_chars(text_content),
                "searchTopK": search_top_k,
                "maxTables": max_tables,
            },
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )
        return [TableContext.model_validate(r["result"]) for r in results]
