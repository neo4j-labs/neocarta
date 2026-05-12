"""Hybrid search bridged through BusinessTerm tags, registered per label."""

from fastmcp import FastMCP
from neo4j import AsyncDriver, RoutingControl

from ...enrichment.embeddings import OpenAIEmbeddingsConnector
from ..cypher import (
    get_context_by_column_business_term_hybrid_search_cypher,
    get_context_by_table_business_term_hybrid_search_cypher,
)
from ..models import TableContext


def register_table_tool(
    server: FastMCP,
    neo4j_driver: AsyncDriver,
    neo4j_database: str,
    embedder: OpenAIEmbeddingsConnector,
) -> None:
    """Register the table-level BT-bridged hybrid search tool."""

    @server.tool()
    async def get_context_by_table_business_term_hybrid_search(
        text_content: str,
        max_tables: int = 5,
    ) -> list[TableContext]:
        """
        Find tables via vector + full-text search, with the full-text branch bridged through BusinessTerm tags.

        The full-text branch matches BusinessTerm nodes and then surfaces tables that
        (a) also match the query in the table full-text index AND (b) are TAGGED_WITH
        one of those BusinessTerm nodes. Combined with the vector branch via per-branch
        normalization and max-per-table merge. Use this tool when the query is phrased
        in business-glossary terms (e.g. "average order value") that may not appear
        verbatim in table metadata but are tagged to relevant tables.

        Parameters
        ----------
        text_content: str
            Natural-language and/or business-term query. The same string is used for
            the embedding lookup and both full-text branches.
        max_tables: int
            Maximum number of tables to return.
        """
        embedding = await embedder._create_embedding_async(text_content)
        cypher = get_context_by_table_business_term_hybrid_search_cypher()
        results = await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={
                "queryEmbedding": embedding,
                "queryText": text_content,
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
    embedder: OpenAIEmbeddingsConnector,
) -> None:
    """Register the column-level BT-bridged hybrid search tool."""

    @server.tool()
    async def get_context_by_column_business_term_hybrid_search(
        text_content: str,
        max_tables: int = 5,
    ) -> list[TableContext]:
        """
        Find tables via vector + full-text search at the Column level, with the full-text branch bridged through BusinessTerm tags.

        The full-text branch matches BusinessTerm nodes and then surfaces columns that
        (a) also match the query in the column full-text index AND (b) are TAGGED_WITH
        one of those BusinessTerm nodes. Combined with the column-vector branch via
        per-branch normalization and max-per-column merge, then aggregated to the parent
        table by average score. Use this tool when business-glossary phrasing maps onto
        field-level concepts via column tags.

        Parameters
        ----------
        text_content: str
            Natural-language and/or business-term query. The same string is used for
            the embedding lookup and both full-text branches.
        max_tables: int
            Maximum number of tables to return.
        """
        embedding = await embedder._create_embedding_async(text_content)
        cypher = get_context_by_column_business_term_hybrid_search_cypher()
        results = await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={
                "queryEmbedding": embedding,
                "queryText": text_content,
                "maxTables": max_tables,
            },
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )
        return [TableContext.model_validate(r["result"]) for r in results]
