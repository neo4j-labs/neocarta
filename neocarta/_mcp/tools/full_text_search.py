"""Full-text-search-based MCP tools, registered per label."""

from fastmcp import FastMCP
from neo4j import AsyncDriver, RoutingControl

from ..cypher import (
    get_context_by_column_full_text_search_cypher,
    get_context_by_table_full_text_search_cypher,
)
from ..models import TableContext


def register_table_tool(
    server: FastMCP,
    neo4j_driver: AsyncDriver,
    neo4j_database: str,
) -> None:
    """Register the table-level full-text search tool."""

    @server.tool()
    async def get_context_by_table_full_text_search(
        text_content: str,
        max_tables: int = 10,
    ) -> list[TableContext]:
        """
        Find tables by full-text matching on table name and description.

        Prefer this tool when the query contains literal table-name tokens or
        specific keywords likely to appear verbatim in table metadata (e.g.
        "orders", "fct_revenue"). No embeddings are required.

        Parameters
        ----------
        text_content: str
            The full-text search expression. Supports Lucene query syntax.
        max_tables: int
            Maximum number of tables to return.
        """
        cypher = get_context_by_table_full_text_search_cypher()
        results = await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={"queryText": text_content, "maxTables": max_tables},
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )
        return [TableContext.model_validate(r["result"]) for r in results]


def register_column_tool(
    server: FastMCP,
    neo4j_driver: AsyncDriver,
    neo4j_database: str,
) -> None:
    """Register the column-level full-text search tool."""

    @server.tool()
    async def get_context_by_column_full_text_search(
        text_content: str,
        max_tables: int = 5,
    ) -> list[TableContext]:
        """
        Find tables by full-text matching on column name and description.

        Prefer this tool when the query references specific column-name tokens
        (e.g. "customer_id", "total_amount"). Matching columns are aggregated up
        to their parent tables and ranked by average column score. No embeddings
        are required.

        Parameters
        ----------
        text_content: str
            The full-text search expression. Supports Lucene query syntax.
        max_tables: int
            Maximum number of tables to return.
        """
        cypher = get_context_by_column_full_text_search_cypher()
        results = await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={"queryText": text_content, "maxTables": max_tables},
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )
        return [TableContext.model_validate(r["result"]) for r in results]
