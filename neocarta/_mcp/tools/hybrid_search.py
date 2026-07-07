"""Hybrid (vector + full-text on same node label) MCP tools, registered per label."""

from fastmcp import FastMCP
from neo4j import AsyncDriver, RoutingControl

from ...connectors.utils.generate_id import generate_osi_semantic_model_id
from ...enrichment.embeddings import LiteLLMEmbeddingsConnector
from ..cypher import (
    get_context_by_column_hybrid_search_cypher,
    get_context_by_metric_hybrid_search_cypher,
    get_context_by_table_hybrid_search_cypher,
)
from ..models import MetricContext, TableContext
from ..utils import escape_lucene_query


def register_table_tool(
    server: FastMCP,
    neo4j_driver: AsyncDriver,
    neo4j_database: str,
    embedder: LiteLLMEmbeddingsConnector,
) -> None:
    """Register the table-level hybrid (vector + full-text) search tool."""

    @server.tool()
    async def get_context_by_table_hybrid_search(
        text_content: str,
        max_tables: int = 5,
        search_top_k: int = 10,
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
            Maximum number of tables in the returned context.
        search_top_k: int
            Number of table candidates each search branch returns before
            ranking. Increase to widen recall; decrease to tighten precision.
        """
        embedding = await embedder._create_embedding_async(text_content)
        cypher = get_context_by_table_hybrid_search_cypher()
        results = await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={
                "queryEmbedding": embedding,
                "queryText": escape_lucene_query(text_content),
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
    """Register the column-level hybrid (vector + full-text) search tool."""

    @server.tool()
    async def get_context_by_column_hybrid_search(
        text_content: str,
        max_tables: int = 5,
        search_top_k: int = 10,
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
            Maximum number of tables in the returned context.
        search_top_k: int
            Number of column candidates each search branch returns before being
            grouped to parent tables. Increase to widen recall; decrease to tighten precision.
        """
        embedding = await embedder._create_embedding_async(text_content)
        cypher = get_context_by_column_hybrid_search_cypher()
        results = await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={
                "queryEmbedding": embedding,
                "queryText": escape_lucene_query(text_content),
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
    """Register the metric-level hybrid (vector + full-text) search tool."""

    @server.tool()
    async def get_context_by_metric_hybrid_search(
        text_content: str,
        max_metrics: int = 10,
        search_top_k: int = 10,
        domain_name: str | None = None,
    ) -> list[MetricContext]:
        """
        Find OSI metrics via a hybrid vector + full-text search at the metric level.

        Anchors on metrics using two parallel signals — embedding similarity and full-text
        matching on metric name/description — normalizes each signal and merges them per
        metric by taking the stronger of the two. Each surviving anchor is returned with its
        full context: owning domain, all dialect-specific SQL expressions, business-term
        synonyms, and aspects.

        Prefer this tool when the query mixes conceptual phrasing with literal tokens you
        expect to see verbatim in metric metadata.

        Parameters
        ----------
        text_content: str
            Natural-language and/or keyword query. The same string is used for both the
            embedding lookup and the full-text search.
        max_metrics: int
            Maximum number of metrics in the returned context.
        search_top_k: int
            Number of metric candidates each search branch returns before ranking. Increase
            to widen recall; decrease to tighten precision.
        domain_name: str | None
            When set, restrict the search to metrics owned by that domain (semantic model).
        """
        embedding = await embedder._create_embedding_async(text_content)
        cypher = get_context_by_metric_hybrid_search_cypher()
        results = await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={
                "queryEmbedding": embedding,
                "queryText": escape_lucene_query(text_content),
                "searchTopK": search_top_k,
                "maxMetrics": max_metrics,
                "domainId": generate_osi_semantic_model_id(domain_name) if domain_name else None,
            },
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )
        return [MetricContext.model_validate(r["result"]) for r in results]
