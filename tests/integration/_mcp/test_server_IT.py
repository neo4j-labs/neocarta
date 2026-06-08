"""Integration tests for the MCP server tools."""

import asyncio
import json

from fastmcp import Client
from neo4j import AsyncGraphDatabase

from neocarta._mcp.server import create_mcp_server
from tests.integration._mcp.conftest import MockEmbeddingsConnector

DATABASE_NAME = "neo4j"


async def _call_tool(
    neo4j_connection: dict, tool_name: str, args: dict | None = None
) -> list[dict]:
    """Create async MCP resources, call a tool, and return the parsed result.

    A fresh async driver and mock embedder are created within each call so
    they share the same event loop created by asyncio.run().
    """
    driver = AsyncGraphDatabase.driver(
        neo4j_connection["uri"],
        auth=(neo4j_connection["username"], neo4j_connection["password"]),
    )
    try:
        embedder = MockEmbeddingsConnector(neo4j_driver=driver, database_name=DATABASE_NAME)
        server = await create_mcp_server(driver, DATABASE_NAME, embedder)
        async with Client(server) as client:
            result = await client.call_tool(tool_name, args or {})
            if not result.content:
                return []
            return json.loads(result.content[0].text)
    finally:
        await driver.close()


async def _list_registered_tools(neo4j_connection: dict) -> set[str]:
    """Connect to the MCP server and return the set of registered tool names."""
    driver = AsyncGraphDatabase.driver(
        neo4j_connection["uri"],
        auth=(neo4j_connection["username"], neo4j_connection["password"]),
    )
    try:
        embedder = MockEmbeddingsConnector(neo4j_driver=driver, database_name=DATABASE_NAME)
        server = await create_mcp_server(driver, DATABASE_NAME, embedder)
        async with Client(server) as client:
            tools = await client.list_tools()
            return {t.name for t in tools}
    finally:
        await driver.close()


def test_list_schemas_returns_all_schemas(neo4j_connection, loaded_graph):
    """list_schemas returns one record per schema with the correct database name."""
    data = asyncio.run(_call_tool(neo4j_connection, "list_schemas"))

    assert len(data) == 2
    schema_names = {r["schema_name"] for r in data}
    assert schema_names == {"sales", "analytics"}
    for record in data:
        assert record["database_name"] == "my-project"


def test_list_tables_by_schema_returns_tables(neo4j_connection, loaded_graph):
    """list_tables_by_schema returns the correct tables for a given schema."""
    data = asyncio.run(
        _call_tool(neo4j_connection, "list_tables_by_schema", {"schema_name": "sales"})
    )

    assert len(data) == 1
    record = data[0]
    assert record["schema_name"] == "sales"
    assert set(record["table_names"]) == {"orders", "customers"}


def test_list_tables_by_schema_unknown_returns_empty(neo4j_connection, loaded_graph):
    """list_tables_by_schema returns an empty list for an unknown schema."""
    data = asyncio.run(
        _call_tool(neo4j_connection, "list_tables_by_schema", {"schema_name": "unknown"})
    )

    assert data == []


def test_get_full_metadata_schema_returns_all_tables(neo4j_connection, loaded_graph):
    """get_full_metadata_schema returns every table with all columns populated."""
    data = asyncio.run(_call_tool(neo4j_connection, "get_full_metadata_schema"))

    assert len(data) == 3
    table_names = {r["table_name"] for r in data}
    assert table_names == {"orders", "customers", "summary"}

    for record in data:
        assert record["database_name"] == "my-project"
        assert len(record["columns"]) > 0

    orders = next(r for r in data if r["table_name"] == "orders")
    assert {c["column_name"] for c in orders["columns"]} == {"order_id", "customer_id", "total"}

    customer_id_col = next(c for c in orders["columns"] if c["column_name"] == "customer_id")
    assert "customers.customer_id" in customer_id_col["references"]


def test_per_label_priority_registers_bt_hybrid_tools(neo4j_connection, loaded_graph):
    """With vector + full-text + BusinessTerm indexes loaded, Table and Column tools
    register at the BT-hybrid tier; lower-tier tools for those labels are not exposed.
    """
    tools = asyncio.run(_list_registered_tools(neo4j_connection))

    assert "get_context_by_table_business_term_hybrid_search" in tools
    assert "get_context_by_column_business_term_hybrid_search" in tools

    lower_tier_for_table = {
        "get_context_by_table_hybrid_search",
        "get_context_by_table_full_text_search",
        "get_context_by_table_vector_search",
    }
    lower_tier_for_column = {
        "get_context_by_column_hybrid_search",
        "get_context_by_column_full_text_search",
        "get_context_by_column_vector_search",
    }
    assert tools.isdisjoint(lower_tier_for_table)
    assert tools.isdisjoint(lower_tier_for_column)

    assert "get_context_by_schema_and_table_vector_search" in tools
    assert {"list_schemas", "list_tables_by_schema", "get_full_metadata_schema"}.issubset(tools)


def test_get_context_by_schema_and_table_vector_search(neo4j_connection, loaded_graph):
    """Schema/table vector search returns tables with their columns populated."""
    data = asyncio.run(
        _call_tool(
            neo4j_connection,
            "get_context_by_schema_and_table_vector_search",
            {"text_content": "sales orders customers", "max_tables": 5},
        )
    )

    assert len(data) > 0
    for record in data:
        assert record["database_name"] == "my-project"
        assert len(record["columns"]) > 0
        assert record["num_columns"] == len(record["columns"])
        assert record["table_score"] is not None
        assert record["table_score"] > 0.5
        assert record["schema_score"] is not None
        assert record["schema_score"] > 0.5


def test_get_context_by_table_business_term_hybrid_search(neo4j_connection, loaded_graph):
    """BT-bridged hybrid table search returns tables with columns and a merged score."""
    data = asyncio.run(
        _call_tool(
            neo4j_connection,
            "get_context_by_table_business_term_hybrid_search",
            {"text_content": "orders", "max_tables": 5},
        )
    )

    assert len(data) > 0
    table_names = {r["table_name"] for r in data}
    assert "orders" in table_names

    for record in data:
        assert record["database_name"] == "my-project"
        assert len(record["columns"]) > 0
        assert record["num_columns"] == len(record["columns"])
        assert record["table_score"] is not None
        assert record["table_score"] > 0


def test_get_context_by_column_business_term_hybrid_search(neo4j_connection, loaded_graph):
    """BT-bridged hybrid column search aggregates matching columns up to their parent tables."""
    data = asyncio.run(
        _call_tool(
            neo4j_connection,
            "get_context_by_column_business_term_hybrid_search",
            {"text_content": "name", "max_tables": 5},
        )
    )

    assert len(data) > 0
    for record in data:
        assert record["database_name"] == "my-project"
        assert len(record["columns"]) > 0
        assert record["num_columns"] == len(record["columns"])
        assert record["column_avg_score"] is not None
        assert record["column_avg_score"] > 0
