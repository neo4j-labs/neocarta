import json
from unittest.mock import MagicMock

import pandas as pd
import pytest
import yaml

from neocarta.connectors.databricks.metrics.extract import DatabricksMetricsExtractor
from neocarta.connectors.databricks.metrics.transform import DatabricksMetricsTransformer

CATALOG = "main"
SCHEMA = "sales"
VIEW = "orders_metrics"
FULL_NAME = f"{CATALOG}.{SCHEMA}.{VIEW}"

# A metric view's stored YAML, as returned by `DESCRIBE TABLE EXTENDED ... AS JSON`
# in the `view_text` field. Databricks normalizes the spec's `fields` keyword to
# `dimensions` on storage, so the realistic round-trip uses `dimensions`.
METRIC_VIEW_YAML = """version: "1.1"
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


def describe_json(view_text: str | None, *, name: str = VIEW) -> str:
    """Build a `DESCRIBE TABLE EXTENDED ... AS JSON` json_metadata payload."""
    payload: dict = {"table_name": name, "type": "METRIC_VIEW", "comment": f"{name} comment"}
    if view_text is not None:
        payload["view_text"] = view_text
    return json.dumps(payload)


def make_connection(views: dict[str, str | None]) -> MagicMock:
    """Build a mock databricks.sql connection that mimics the real read path.

    ``views`` maps each metric-view name to the ``view_text`` it should report
    (or ``None`` to simulate a definition with no ``view_text``). The mock
    dispatches on the SQL: the ``information_schema.tables`` listing returns the
    metric-view names, and ``DESCRIBE TABLE EXTENDED <name> AS JSON`` returns that
    view's payload.
    """
    connection = MagicMock()

    def make_cursor() -> MagicMock:
        cursor = MagicMock()
        state: dict[str, str] = {}

        def execute(sql: str, params: dict | None = None) -> None:
            state["sql"] = sql

        def to_pandas() -> pd.DataFrame:
            sql = state.get("sql", "")
            if "information_schema" in sql and "table_type" in sql:
                rows = [(name, f"{name} comment") for name in views]
                return pd.DataFrame(rows, columns=["table_name", "table_comment"])
            if "DESCRIBE TABLE EXTENDED" in sql:
                name = next((n for n in views if f"`{n}`" in sql), None)
                return pd.DataFrame(
                    [[describe_json(views.get(name), name=name or "")]], columns=["json_metadata"]
                )
            return pd.DataFrame()

        cursor.execute.side_effect = execute
        cursor.fetchall_arrow.return_value.to_pandas.side_effect = to_pandas
        return cursor

    connection.cursor.side_effect = make_cursor
    return connection


def make_failing_connection(exc: Exception) -> MagicMock:
    """A mock connection whose cursor.execute raises ``exc`` (one shared cursor)."""
    connection = MagicMock()
    cursor = MagicMock()
    cursor.execute.side_effect = exc
    connection.cursor.return_value = cursor
    return connection


@pytest.fixture
def mock_databricks_connection() -> MagicMock:
    """A mock connection serving one metric view (the standard fixture)."""
    return make_connection({VIEW: METRIC_VIEW_YAML})


@pytest.fixture
def metrics_extractor(mock_databricks_connection: MagicMock) -> DatabricksMetricsExtractor:
    """A DatabricksMetricsExtractor wired to the mock connection."""
    return DatabricksMetricsExtractor(connection=mock_databricks_connection, catalog=CATALOG)


@pytest.fixture
def metrics_transformer() -> DatabricksMetricsTransformer:
    """A fresh DatabricksMetricsTransformer."""
    return DatabricksMetricsTransformer()


@pytest.fixture
def sample_metric_views() -> list[dict]:
    """The transformer's input: one parsed metric view.

    Uses the spec's ``fields`` keyword (the extractor/IT fixtures use the stored
    ``dimensions`` form), so the transformer is covered for both spellings.
    """
    definition = yaml.safe_load(METRIC_VIEW_YAML)
    # Re-key dimensions -> fields to exercise the spec keyword here.
    definition["fields"] = definition.pop("dimensions")
    return [
        {
            "full_name": FULL_NAME,
            "catalog": CATALOG,
            "schema": SCHEMA,
            "name": VIEW,
            "comment": "Unity Catalog object comment",
            "definition": definition,
        }
    ]
