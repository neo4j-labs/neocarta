"""Vector-search-based MCP tools, registered per label."""

from fastmcp import FastMCP
from neo4j import AsyncDriver, RoutingControl

from ...enrichment.embeddings import OpenAIEmbeddingsConnector
from ..cypher import (
    get_context_by_column_vector_search_cypher,
    get_context_by_schema_and_table_vector_search_cypher,
    get_context_by_table_vector_search_cypher,
)
from ..models import TableContext


def register_column_tool(
    server: FastMCP,
    neo4j_driver: AsyncDriver,
    neo4j_database: str,
    embedder: OpenAIEmbeddingsConnector,
) -> None:
    """Register the column-level vector similarity tool."""

    @server.tool()
    async def get_context_by_column_vector_search(
        text_content: str,
        max_tables: int = 5,
    ) -> list[TableContext]:
        """
        Find tables whose columns are semantically similar to the provided text.

        Prefer this tool when the query references specific field or column names
        (e.g. "customer email", "order total"). Matches are ranked by average
        column embedding similarity and traversed up to the parent table.
        Note: requires that Column nodes have the embedding property set.

        Parameters
        ----------
        text_content: str
            Natural-language description or query to search for semantically
            similar columns.
        max_tables: int
            Maximum number of tables to return.
        """
        embedding = await embedder._create_embedding_async(text_content)
        cypher = get_context_by_column_vector_search_cypher()
        results = await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={"queryEmbedding": embedding, "maxTables": max_tables},
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )
        return [TableContext.model_validate(r["result"]) for r in results]


def register_table_tool(
    server: FastMCP,
    neo4j_driver: AsyncDriver,
    neo4j_database: str,
    embedder: OpenAIEmbeddingsConnector,
) -> None:
    """Register the table-level vector similarity tool."""

    @server.tool()
    async def get_context_by_table_vector_search(
        text_content: str,
        max_tables: int = 10,
    ) -> list[TableContext]:
        """
        Find tables that are semantically similar to the provided text.

        Prefer this tool when the query describes a general concept or entity
        (e.g. "customers", "sales transactions"). Matches are ranked by table
        embedding similarity.
        Note: requires that Table nodes have the embedding property set.

        Parameters
        ----------
        text_content: str
            Natural-language description or query to search for semantically
            similar tables.
        max_tables: int
            Maximum number of tables to return.
        """
        embedding = await embedder._create_embedding_async(text_content)
        cypher = get_context_by_table_vector_search_cypher()
        results = await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={"queryEmbedding": embedding, "maxTables": max_tables},
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )
        return [TableContext.model_validate(r["result"]) for r in results]


def register_schema_tool(
    server: FastMCP,
    neo4j_driver: AsyncDriver,
    neo4j_database: str,
    embedder: OpenAIEmbeddingsConnector,
) -> None:
    """Register the schema+table vector similarity tool."""

    @server.tool()
    async def get_context_by_schema_and_table_vector_search(
        text_content: str,
        max_tables: int = 5,
    ) -> list[TableContext]:
        """
        Find tables by matching both schema and table embeddings to the provided text.

        Prefer this tool when the query is broad and may span multiple schemas and tables
        (e.g. "everything related to billing").
        First finds similar schemas, then filters to tables within those schemas whose
        embeddings are near or better than the schema score.
        Note: requires that `Schema` and `Table` nodes have the `embedding` property set.

        Parameters
        ----------
        text_content: str
            Natural-language description or query to search for semantically
            similar schemas and tables.
        max_tables: int
            Maximum number of tables to return, ordered by descending schema
            then table similarity score.
        """
        embedding = await embedder._create_embedding_async(text_content)
        cypher = get_context_by_schema_and_table_vector_search_cypher()
        results = await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={"queryEmbedding": embedding, "maxTables": max_tables},
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )
        return [TableContext.model_validate(r["result"]) for r in results]
