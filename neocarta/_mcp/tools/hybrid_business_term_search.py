"""Hybrid search bridged through BusinessTerm tags, registered per label."""

from fastmcp import FastMCP
from neo4j import AsyncDriver, RoutingControl

from ...enrichment.embeddings import LiteLLMEmbeddingsConnector
from ..cypher import (
    get_context_by_column_business_term_hybrid_search_cypher,
    get_context_by_table_business_term_hybrid_search_cypher,
)
from ..models import TableContext
from ..utils import remove_lucene_chars


def register_table_tool(
    server: FastMCP,
    neo4j_driver: AsyncDriver,
    neo4j_database: str,
    embedder: LiteLLMEmbeddingsConnector,
) -> None:
    """Register the table-level BT-bridged hybrid search tool."""

    @server.tool()
    async def get_context_by_table_business_term_hybrid_search(
        text_content: str,
        max_tables: int = 5,
        search_top_k: int = 10,
    ) -> list[TableContext]:
        """
        Find tables via vector + full-text search, with the full-text branch routed through business-glossary terms.

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
        embedding = await embedder._create_embedding_async(text_content)
        cypher = get_context_by_table_business_term_hybrid_search_cypher()
        results = await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={
                "queryEmbedding": embedding,
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
    """Register the column-level BT-bridged hybrid search tool."""

    @server.tool()
    async def get_context_by_column_business_term_hybrid_search(
        text_content: str,
        max_tables: int = 5,
        search_top_k: int = 10,
    ) -> list[TableContext]:
        """
        Find tables via vector + full-text search at the column level, with the full-text branch routed through business-glossary terms.

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
        embedding = await embedder._create_embedding_async(text_content)
        cypher = get_context_by_column_business_term_hybrid_search_cypher()
        results = await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={
                "queryEmbedding": embedding,
                "queryText": remove_lucene_chars(text_content),
                "searchTopK": search_top_k,
                "maxTables": max_tables,
            },
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )
        return [TableContext.model_validate(r["result"]) for r in results]
