"""Hybrid (vector + full-text on same node label) MCP tools, registered per label."""

from fastmcp import FastMCP
from neo4j import AsyncDriver, RoutingControl

from ...enrichment.embeddings import OpenAIEmbeddingsConnector
from ..cypher import (
    get_context_by_column_hybrid_search_cypher,
    get_context_by_table_hybrid_search_cypher,
)
from ..models import TableContext


def register_table_tool(
    server: FastMCP,
    neo4j_driver: AsyncDriver,
    neo4j_database: str,
    embedder: OpenAIEmbeddingsConnector,
) -> None:
    """Register the table-level hybrid (vector + full-text) search tool."""

    @server.tool()
    async def get_context_by_table_hybrid_search(
        text_content: str,
        max_tables: int = 5,
    ) -> list[TableContext]:
        """
        Find tables via a hybrid vector + full-text search at the table level.

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
            Maximum number of tables to return.
        """
        embedding = await embedder._create_embedding_async(text_content)
        cypher = get_context_by_table_hybrid_search_cypher()
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
    """Register the column-level hybrid (vector + full-text) search tool."""

    @server.tool()
    async def get_context_by_column_hybrid_search(
        text_content: str,
        max_tables: int = 5,
    ) -> list[TableContext]:
        """
        Find tables via a hybrid vector + full-text search at the column level.

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
            Maximum number of tables to return.
        """
        embedding = await embedder._create_embedding_async(text_content)
        cypher = get_context_by_column_hybrid_search_cypher()
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
