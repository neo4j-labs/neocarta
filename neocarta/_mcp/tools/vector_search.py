"""Vector-search-based MCP tools, registered per label."""

from fastmcp import FastMCP
from neo4j import AsyncDriver, RoutingControl

from ...connectors.utils.generate_id import generate_osi_semantic_model_id
from ...enrichment.embeddings import LiteLLMEmbeddingsConnector
from ..cypher import (
    get_context_by_column_vector_search_cypher,
    get_context_by_metric_vector_search_cypher,
    get_context_by_schema_and_table_vector_search_cypher,
    get_context_by_table_vector_search_cypher,
)
from ..models import MetricContext, TableContext


def register_column_tool(
    server: FastMCP,
    neo4j_driver: AsyncDriver,
    neo4j_database: str,
    embedder: LiteLLMEmbeddingsConnector,
) -> None:
    """Register the column-level vector similarity tool."""

    @server.tool()
    async def get_context_by_column_vector_search(
        text_content: str,
        max_tables: int = 5,
        search_top_k: int = 10,
    ) -> list[TableContext]:
        """
        Find tables whose columns are semantically similar to the provided text.

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
        embedding = await embedder._create_embedding_async(text_content)
        cypher = get_context_by_column_vector_search_cypher()
        results = await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={
                "queryEmbedding": embedding,
                "searchTopK": search_top_k,
                "maxTables": max_tables,
            },
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )
        return [TableContext.model_validate(r["result"]) for r in results]


def register_table_tool(
    server: FastMCP,
    neo4j_driver: AsyncDriver,
    neo4j_database: str,
    embedder: LiteLLMEmbeddingsConnector,
) -> None:
    """Register the table-level vector similarity tool."""

    @server.tool()
    async def get_context_by_table_vector_search(
        text_content: str,
        max_tables: int = 10,
        search_top_k: int = 10,
    ) -> list[TableContext]:
        """
        Find tables that are semantically similar to the provided text.

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
        embedding = await embedder._create_embedding_async(text_content)
        cypher = get_context_by_table_vector_search_cypher()
        results = await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={
                "queryEmbedding": embedding,
                "searchTopK": search_top_k,
                "maxTables": max_tables,
            },
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )
        return [TableContext.model_validate(r["result"]) for r in results]


def register_metric_tool(
    server: FastMCP,
    neo4j_driver: AsyncDriver,
    neo4j_database: str,
    embedder: LiteLLMEmbeddingsConnector,
) -> None:
    """Register the metric-level vector similarity tool."""

    @server.tool()
    async def get_context_by_metric_vector_search(
        text_content: str,
        max_metrics: int = 10,
        search_top_k: int = 10,
        domain_name: str | None = None,
    ) -> list[MetricContext]:
        """
        Find OSI metrics that are semantically similar to the provided text.

        Anchors on the closest matching metrics by embedding similarity over metric
        name/description, then returns each metric's full context: owning domain, all
        dialect-specific SQL expressions, business-term synonyms, and aspects. A metric
        carries a vetted, dialect-specific definition, so prefer this for conceptual asks
        ("annual recurring revenue", "active headcount") where reusing the canonical
        definition beats re-deriving it from raw columns.

        Parameters
        ----------
        text_content: str
            Natural-language description or query to search for semantically similar
            metrics.
        max_metrics: int
            Maximum number of metrics in the returned context.
        search_top_k: int
            Number of metric candidates the vector index returns before ranking. Increase
            to widen recall; decrease to tighten precision.
        domain_name: str | None
            When set, restrict the search to metrics owned by that domain (semantic model).
        """
        embedding = await embedder._create_embedding_async(text_content)
        cypher = get_context_by_metric_vector_search_cypher()
        results = await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={
                "queryEmbedding": embedding,
                "searchTopK": search_top_k,
                "maxMetrics": max_metrics,
                "domainId": generate_osi_semantic_model_id(domain_name) if domain_name else None,
            },
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )
        return [MetricContext.model_validate(r["result"]) for r in results]


def register_schema_tool(
    server: FastMCP,
    neo4j_driver: AsyncDriver,
    neo4j_database: str,
    embedder: LiteLLMEmbeddingsConnector,
) -> None:
    """Register the schema+table vector similarity tool."""

    @server.tool()
    async def get_context_by_schema_and_table_vector_search(
        text_content: str,
        max_tables: int = 5,
        search_top_k: int = 5,
    ) -> list[TableContext]:
        """
        Find tables by matching both schema and table embeddings to the provided text.

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
        embedding = await embedder._create_embedding_async(text_content)
        cypher = get_context_by_schema_and_table_vector_search_cypher()
        results = await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={
                "queryEmbedding": embedding,
                "searchTopK": search_top_k,
                "maxTables": max_tables,
            },
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )
        return [TableContext.model_validate(r["result"]) for r in results]
