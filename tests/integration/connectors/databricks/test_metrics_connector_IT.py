"""Integration test for the Databricks metric-views connector.

The Databricks SQL warehouse is mocked with a connection that mimics the real
read path — metric views are listed from ``information_schema.tables``
(``table_type='METRIC_VIEW'``) and each definition is read via
``DESCRIBE TABLE EXTENDED … AS JSON`` (the ``view_text`` field). Neo4j is real (a
testcontainer via the shared ``neo4j_driver`` fixture). The full
extract -> transform -> load pipeline runs against Neo4j and is verified with
Cypher, exercising the real ``OsiNeo4jLoader`` writes, secondary-label MERGEs,
constraints, indexes, and the neocarta graph metadata node.
"""

import json
from unittest.mock import MagicMock

import pandas as pd

from neocarta.connectors.databricks import DatabricksMetricsConnector

CATALOG = "main"
SCHEMA = "sales"
VIEW = "orders_metrics"
FULL_NAME = f"{CATALOG}.{SCHEMA}.{VIEW}"

# Stored metric-view YAML (Databricks stores the spec's `fields` as `dimensions`).
_METRIC_VIEW_YAML = """version: "1.1"
comment: Order metrics
source: main.sales.orders
dimensions:
  - name: order_status
    expr: o_orderstatus
    display_name: Order Status
    synonyms: [status, fulfillment status]
measures:
  - name: total_revenue
    expr: SUM(o_totalprice)
    comment: Gross revenue from all orders
    display_name: Total Revenue
    synonyms: [revenue, total sales]
  - name: order_count
    expr: COUNT(1)
"""


def _mock_connection() -> MagicMock:
    """A databricks.sql connection mimicking list + DESCRIBE-AS-JSON for one metric view."""
    describe_payload = json.dumps(
        {"table_name": VIEW, "type": "METRIC_VIEW", "view_text": _METRIC_VIEW_YAML}
    )

    connection = MagicMock()

    def make_cursor() -> MagicMock:
        cursor = MagicMock()
        state: dict[str, str] = {}

        def execute(sql: str, params: dict | None = None) -> None:
            state["sql"] = sql

        def to_pandas() -> pd.DataFrame:
            sql = state.get("sql", "")
            if "information_schema" in sql and "table_type" in sql:
                return pd.DataFrame(
                    [(VIEW, "Order metrics view")], columns=["table_name", "table_comment"]
                )
            if "DESCRIBE TABLE EXTENDED" in sql:
                return pd.DataFrame([[describe_payload]], columns=["json_metadata"])
            return pd.DataFrame()

        cursor.execute.side_effect = execute
        cursor.fetchall_arrow.return_value.to_pandas.side_effect = to_pandas
        return cursor

    connection.cursor.side_effect = make_cursor
    return connection


def _count(session, query):
    return session.run(query).single()["c"]


def test_ingest_loads_metric_view_graph(neo4j_driver):
    """A full ingest writes the OsiSemanticModel/Metric/OsiColumn/Expression graph."""
    connector = DatabricksMetricsConnector(
        connection=_mock_connection(), catalog=CATALOG, neo4j_driver=neo4j_driver
    )
    connector.ingest(schema=SCHEMA)

    with neo4j_driver.session(database="neo4j") as session:
        # The metric view -> one OsiSemanticModel (a :Domain subtype).
        sm = session.run(
            "MATCH (d:Domain:OsiSemanticModel {id:$id}) RETURN d.name AS name, d.osi_version AS v",
            id=FULL_NAME,
        ).single()
        assert sm["name"] == FULL_NAME
        assert sm["v"] == "1.1"

        # The view as a dataset -> one OsiTable carrying the source pointer.
        table = session.run(
            "MATCH (t:Table:OsiTable {id:$id}) RETURN t.source AS source", id=FULL_NAME
        ).single()
        assert table["source"] == FULL_NAME
        assert _count(session, "MATCH (t:Table) RETURN count(t) AS c") == 1

        # Measures -> Metric nodes (one per measure) under the model.
        assert _count(session, "MATCH (m:Metric) RETURN count(m) AS c") == 2
        assert _count(session, "MATCH (:Domain)-[:HAS_METRIC]->(:Metric) RETURN count(*) AS c") == 2

        # Dimensions -> OsiColumn under the table.
        col = session.run(
            "MATCH (c:Column:OsiColumn {name:'order_status'}) "
            "RETURN c.label AS label, c.is_time_dimension AS itd, c.is_primary_key AS ipk"
        ).single()
        assert col["label"] == "Order Status"
        # Undefined props are omitted (NULL), never written as a fabricated False.
        assert col["itd"] is None
        assert col["ipk"] is None
        assert _count(session, "MATCH (:Table)-[:HAS_COLUMN]->(:Column) RETURN count(*) AS c") == 1

        # Expressions (dialect=databricks): order_status, total_revenue, order_count.
        assert _count(session, "MATCH (e:Expression) RETURN count(e) AS c") == 3
        assert (
            _count(
                session,
                "MATCH (e:Expression) WHERE e.dialect <> 'databricks' RETURN count(e) AS c",
            )
            == 0
        )
        assert (
            _count(session, "MATCH ()-[:HAS_EXPRESSION]->(:Expression) RETURN count(*) AS c") == 3
        )

        # AI context aspects (order_status + total_revenue carry synonyms/display_name).
        assert _count(session, "MATCH (a:Aspect:OsiAiContext) RETURN count(a) AS c") == 2
        assert _count(session, "MATCH ()-[:HAS_ASPECT]->(:Aspect) RETURN count(*) AS c") == 2

        # Synonyms -> BusinessTerm + TAGGED_WITH.
        assert _count(session, "MATCH (b:BusinessTerm) RETURN count(b) AS c") == 4
        assert _count(session, "MATCH ()-[:TAGGED_WITH]->(:BusinessTerm) RETURN count(*) AS c") == 4

        # ingest() records the neocarta graph metadata node.
        assert _count(session, "MATCH (n:__neocarta_graph__) RETURN count(n) AS c") == 1

        # A full-text index over Metric is provisioned (the search surface).
        ft = session.run("SHOW FULLTEXT INDEXES YIELD labelsOrTypes RETURN labelsOrTypes").data()
        assert any("Metric" in (row["labelsOrTypes"] or []) for row in ft)

    # Idempotency: a second ingest MERGEs onto the same nodes (counts unchanged).
    connector.ingest(schema=SCHEMA)
    with neo4j_driver.session(database="neo4j") as session:
        assert _count(session, "MATCH (m:Metric) RETURN count(m) AS c") == 2
        assert _count(session, "MATCH (c:Column:OsiColumn) RETURN count(c) AS c") == 1
        assert _count(session, "MATCH (b:BusinessTerm) RETURN count(b) AS c") == 4
