"""Integration test: get_domain_context / list_domains include OSI query-backed datasets."""

import asyncio
import tempfile
from pathlib import Path

import pytest
from neo4j import GraphDatabase

from neocarta.connectors.osi import OsiConnector
from tests.integration._mcp.conftest import DATABASE_NAME
from tests.integration._mcp.test_server_IT import _call_tool

# A minimal OSI model whose first dataset is query-backed (source is a SQL query, not a
# 3-part identifier) so the query-dataset graph path (Query + USES_COLUMN) is exercised.
_QUERY_MODEL_YAML = """
version: "0.1.1"
semantic_model:
  - name: query_model
    description: A model with one query-backed dataset and one table dataset.
    datasets:
      - name: active_users
        source: "SELECT user_id, signup_at, status FROM warehouse.app.users WHERE active = true"
        ai_context:
          instructions: "Active-users derived view."
        fields:
          - name: user_id
            expression: { dialects: [{ dialect: ANSI_SQL, expression: user_id }] }
          - name: signup_at
            expression: { dialects: [{ dialect: ANSI_SQL, expression: signup_at }] }
            dimension: { is_time: true }
          - name: status
            expression: { dialects: [{ dialect: ANSI_SQL, expression: status }] }
            ai_context:
              instructions: "User status on the active-users view."
      - name: orders
        source: warehouse.app.orders
        primary_key: [order_id]
        fields:
          - name: order_id
            expression: { dialects: [{ dialect: ANSI_SQL, expression: order_id }] }
          - name: user_id
            expression: { dialects: [{ dialect: ANSI_SQL, expression: user_id }] }
          - name: status
            expression: { dialects: [{ dialect: ANSI_SQL, expression: status }] }
            ai_context:
              instructions: "Order fulfillment status."
    relationships:
      - name: orders_to_active_users
        from: orders
        to: active_users
        from_columns: [user_id]
        to_columns: [user_id]
        custom_extensions:
          - vendor_name: DBT
            data: '{"relationship": "orders_to_active_users"}'
    metrics:
      - name: order_count
        description: Count of orders.
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: "COUNT(orders.order_id)"
"""


@pytest.fixture(scope="module")
def osi_query_graph(setup):
    """Load a small OSI model with a query-backed dataset once per module."""
    sync_driver = GraphDatabase.driver(
        setup.get_connection_url(),
        auth=(setup.username, setup.password),
    )
    tmp = Path(tempfile.mkdtemp())
    spec_path = tmp / "query_model.yaml"
    spec_path.write_text(_QUERY_MODEL_YAML)
    try:
        with sync_driver.session(database=DATABASE_NAME) as session:
            session.run("MATCH (n) DETACH DELETE n")
        OsiConnector(neo4j_driver=sync_driver, database_name=DATABASE_NAME).ingest(spec_path)
    finally:
        sync_driver.close()


def test_list_domains_counts_query_dataset(neo4j_connection, osi_query_graph):
    """list_domains counts both the table and query datasets and all their columns."""
    data = asyncio.run(_call_tool(neo4j_connection, "list_domains"))

    assert len(data) == 1
    domain = data[0]
    assert domain["domain_name"] == "query_model"
    assert domain["num_tables"] == 2  # active_users (query) + orders (table)
    assert domain["num_columns"] == 6  # 3 query columns + 3 table columns


def test_get_domain_context_includes_query_dataset(neo4j_connection, osi_query_graph):
    """get_domain_context surfaces a query-backed dataset with its columns (null db/schema)."""
    data = asyncio.run(
        _call_tool(neo4j_connection, "get_domain_context", {"domain_name": "query_model"})
    )

    table_names = {t["table_name"] for t in data["tables"]}
    assert table_names == {"active_users", "orders"}

    active_users = next(t for t in data["tables"] if t["table_name"] == "active_users")
    # A query-backed dataset has no database/schema.
    assert active_users["database_name"] is None
    assert active_users["schema_name"] is None
    assert {c["column_name"] for c in active_users["columns"]} == {
        "user_id",
        "signup_at",
        "status",
    }
    signup = next(c for c in active_users["columns"] if c["column_name"] == "signup_at")
    assert signup["is_time_dimension"] is True

    orders = next(t for t in data["tables"] if t["table_name"] == "orders")
    assert orders["primary_key"] == ["order_id"]


def test_query_dataset_and_column_aspects_embedded_and_scoped(neo4j_connection, osi_query_graph):
    """Aspects on a query-backed dataset and its columns ride along on get_domain_context,
    and same-named columns keep their own dataset's aspect (no cross-dataset fan-out)."""
    data = asyncio.run(
        _call_tool(neo4j_connection, "get_domain_context", {"domain_name": "query_model"})
    )

    active_users = next(t for t in data["tables"] if t["table_name"] == "active_users")
    orders = next(t for t in data["tables"] if t["table_name"] == "orders")

    # The query-backed dataset's own aspect is reachable (HAS_QUERY traversal).
    assert any("Active-users derived view" in a["data"] for a in active_users["aspects"])

    # Each dataset's `status` column carries only its own aspect (column table-scoping).
    active_status = next(c for c in active_users["columns"] if c["column_name"] == "status")
    orders_status = next(c for c in orders["columns"] if c["column_name"] == "status")
    assert any("active-users view" in a["data"] for a in active_status["aspects"])
    assert all("Order fulfillment status" not in a["data"] for a in active_status["aspects"])
    assert any("Order fulfillment status" in a["data"] for a in orders_status["aspects"])


def test_join_aspect_embedded_in_domain_context(neo4j_connection, osi_query_graph):
    """A join's custom_extensions aspect is embedded on get_domain_context().joins[]."""
    data = asyncio.run(
        _call_tool(neo4j_connection, "get_domain_context", {"domain_name": "query_model"})
    )

    assert len(data["joins"]) == 1
    join = data["joins"][0]
    assert join["join_name"] == "orders_to_active_users"
    assert any(
        a["aspect_type"] == "custom_extensions" and "orders_to_active_users" in a["data"]
        for a in join["aspects"]
    )
