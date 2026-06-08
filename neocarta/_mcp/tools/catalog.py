"""Catalog MCP tools (schema/table listing, full metadata dump). Always registered."""

from fastmcp import FastMCP
from neo4j import AsyncDriver, RoutingControl

from ..cypher import (
    get_full_metadata_schema_cypher,
    list_schemas_cypher,
    list_tables_by_schema_cypher,
)
from ..models import ListSchemaRecord, ListTablesBySchemaRecord, TableContext


def register(server: FastMCP, neo4j_driver: AsyncDriver, neo4j_database: str) -> None:
    """Register catalog tools on the MCP server."""

    @server.tool()
    async def list_schemas() -> list[ListSchemaRecord]:
        """
        List all schemas and their databases.

        Use this as the first step when exploring an unfamiliar database or when
        you need a valid schema name to pass to other tools. Returns every schema
        alongside the database it belongs to.
        """
        cypher = list_schemas_cypher()
        return await neo4j_driver.execute_query(
            query_=cypher,
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )

    @server.tool()
    async def list_tables_by_schema(schema_name: str) -> list[ListTablesBySchemaRecord]:
        """
        List all tables for a given schema.

        Use this when you already know the schema name and want to enumerate its
        tables. Call list_schemas first to obtain valid schema names.

        Parameters
        ----------
        schema_name: str
            The name of the schema to list tables for. Use list_schemas to get
            valid schema names.
        """
        cypher = list_tables_by_schema_cypher()
        return await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={"schemaName": schema_name},
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )

    @server.tool()
    async def get_full_metadata_schema() -> list[TableContext]:
        """
        Return the complete metadata schema for every table in the database.

        WARNING: This fetches all tables and all columns without any filtering.
        On databases with many tables this will return a very large payload and
        should only be used for debugging or on small databases. Prefer the
        targeted retrieval tools for normal lookups.
        """
        cypher = get_full_metadata_schema_cypher()
        results = await neo4j_driver.execute_query(
            query_=cypher,
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )
        return [TableContext.model_validate(r["result"]) for r in results]
