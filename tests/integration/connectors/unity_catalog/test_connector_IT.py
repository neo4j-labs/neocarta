"""Integration test for the Unity Catalog schema connector.

The Unity Catalog REST API is mocked with recorded responses; Neo4j is real (a
testcontainer via the shared ``neo4j_driver`` fixture). The connector's owned
``httpx.Client`` is swapped for a fixture-backed mock, then the full
extract -> transform -> load pipeline is driven and verified with Cypher.
"""

from unittest.mock import MagicMock

from neocarta.connectors.unity_catalog import UnityCatalogSchemaConnector

BASE_URL = "http://localhost:8080/api/2.1/unity-catalog"

_CATALOG = {"name": "main", "comment": "Primary catalog"}
_SCHEMAS = {
    "schemas": [{"name": "sales", "catalog_name": "main", "comment": "Sales data"}],
    "next_page_token": "",
}
_TABLES = {
    "tables": [
        {
            "name": "orders",
            "catalog_name": "main",
            "schema_name": "sales",
            "table_type": "MANAGED",
            "comment": "Order facts",
            "columns": [
                {
                    "name": "order_id",
                    "type_text": "bigint",
                    "type_name": "LONG",
                    "nullable": False,
                    "comment": "Order identifier",
                },
                {
                    "name": "amount",
                    "type_text": "decimal(10,2)",
                    "type_name": "DECIMAL",
                    "nullable": True,
                    "comment": None,
                },
            ],
        }
    ],
    "next_page_token": "",
}


def _mock_client():
    """Build a mock httpx client dispatching the recorded payloads."""

    def _response(payload):
        response = MagicMock()
        response.json.return_value = payload
        response.raise_for_status.return_value = None
        return response

    def _get(path, params=None):
        params = params or {}
        if path.startswith("/catalogs/"):
            return _response(_CATALOG)
        if path == "/schemas":
            return _response(_SCHEMAS)
        if path == "/tables":
            if params.get("schema_name") == "sales":
                return _response(_TABLES)
            return _response({"tables": [], "next_page_token": ""})
        msg = f"unexpected request path: {path}"
        raise AssertionError(msg)

    client = MagicMock()
    client.get.side_effect = _get
    return client


def _count(session, query):
    return session.run(query).single()["c"]


def test_ingest_loads_schema_graph(neo4j_driver):
    """A full ingest writes the catalog/schema/table/column graph and HAS_* edges."""
    connector = UnityCatalogSchemaConnector(base_url=BASE_URL, neo4j_driver=neo4j_driver)
    connector.extractor._client = _mock_client()

    connector.ingest("main")

    with neo4j_driver.session(database="neo4j") as session:
        # Nodes
        assert (
            session.run("MATCH (d:Database {id:'main'}) RETURN d.name AS n").single()["n"] == "main"
        )
        assert _count(session, "MATCH (s:Schema {id:'main.sales'}) RETURN count(s) AS c") == 1
        assert _count(session, "MATCH (t:Table {id:'main.sales.orders'}) RETURN count(t) AS c") == 1
        assert _count(session, "MATCH (c:Column) RETURN count(c) AS c") == 2

        # Relationships
        assert (
            _count(session, "MATCH (:Database)-[:HAS_SCHEMA]->(:Schema) RETURN count(*) AS c") == 1
        )
        assert _count(session, "MATCH (:Schema)-[:HAS_TABLE]->(:Table) RETURN count(*) AS c") == 1
        assert _count(session, "MATCH (:Table)-[:HAS_COLUMN]->(:Column) RETURN count(*) AS c") == 2

        # Column type carries the full SQL type from type_text
        col_type = session.run(
            "MATCH (c:Column {id:'main.sales.orders.amount'}) RETURN c.type AS t"
        ).single()["t"]
        assert col_type == "decimal(10,2)"

        # The neocarta graph metadata node is recorded by ingest()
        assert _count(session, "MATCH (n:__neocarta_graph__) RETURN count(n) AS c") == 1
