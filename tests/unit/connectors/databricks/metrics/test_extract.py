"""Unit tests for the Databricks metric-view extractor.

The mock connection mirrors the real read path: metric views are listed from
``information_schema.tables`` (``table_type='METRIC_VIEW'``) and each definition
is read via ``DESCRIBE TABLE EXTENDED … AS JSON`` (the ``view_text`` field).
"""

import pytest

from neocarta.connectors.databricks.metrics.extract import (
    DatabricksMetricsExtractor,
    _parse_view_text,
)
from neocarta.errors import AuthError, ConfigError

from .conftest import (
    CATALOG,
    FULL_NAME,
    METRIC_VIEW_YAML,
    SCHEMA,
    VIEW,
    describe_json,
    make_connection,
    make_failing_connection,
)


def test_requires_connection():
    """A missing connection is a configuration error."""
    with pytest.raises(ConfigError):
        DatabricksMetricsExtractor(connection=None, catalog=CATALOG)


def test_requires_catalog(mock_databricks_connection):
    """A missing catalog is a configuration error."""
    with pytest.raises(ConfigError):
        DatabricksMetricsExtractor(connection=mock_databricks_connection, catalog="")


def test_extract_discovers_metric_views(metrics_extractor):
    """A schema with one metric view yields one parsed MetricViewInfo."""
    result = metrics_extractor.extract_metric_views(schema=SCHEMA)

    assert len(result) == 1
    mv = result[0]
    assert mv["full_name"] == FULL_NAME
    assert mv["catalog"] == CATALOG
    assert mv["schema"] == SCHEMA
    assert mv["name"] == VIEW
    assert mv["definition"]["source"] == "main.sales.orders"
    assert [m["name"] for m in mv["definition"]["measures"]] == ["total_revenue", "order_count"]


def test_extract_caches_result(metrics_extractor):
    """The discovered metric views are cached and exposed via the property."""
    result = metrics_extractor.extract_metric_views(schema=SCHEMA)
    assert metrics_extractor.metric_views == result


def test_extract_no_metric_views_returns_empty():
    """A schema with no METRIC_VIEW objects yields nothing."""
    extractor = DatabricksMetricsExtractor(connection=make_connection({}), catalog=CATALOG)
    assert extractor.extract_metric_views(schema=SCHEMA) == []


def test_extract_skips_view_without_view_text():
    """A listed metric view whose DESCRIBE payload has no view_text is skipped."""
    extractor = DatabricksMetricsExtractor(
        connection=make_connection({VIEW: None}), catalog=CATALOG
    )
    assert extractor.extract_metric_views(schema=SCHEMA) == []


def test_extract_discovers_multiple_metric_views():
    """Multiple metric views are each listed and read."""
    extractor = DatabricksMetricsExtractor(
        connection=make_connection({"a_metrics": METRIC_VIEW_YAML, "b_metrics": METRIC_VIEW_YAML}),
        catalog=CATALOG,
    )
    result = extractor.extract_metric_views(schema=SCHEMA)
    assert sorted(mv["name"] for mv in result) == ["a_metrics", "b_metrics"]


def test_quote_identifier_rejects_backtick():
    """A catalog name containing a backtick is rejected before any query runs."""
    extractor = DatabricksMetricsExtractor(connection=make_connection({}), catalog="ba`d")
    with pytest.raises(ConfigError):
        extractor.extract_metric_views(schema=SCHEMA)


def test_databricks_error_maps_to_auth_error():
    """A databricks.sql error with an auth signal is mapped to AuthError."""
    from databricks.sql.exc import OperationalError

    extractor = DatabricksMetricsExtractor(
        connection=make_failing_connection(OperationalError("Unauthorized: invalid access token")),
        catalog=CATALOG,
    )
    with pytest.raises(AuthError):
        extractor.extract_metric_views(schema=SCHEMA)


def test_cursor_closed_even_on_error():
    """The cursor is closed even when the query raises."""
    from databricks.sql.exc import OperationalError

    connection = make_failing_connection(OperationalError("boom"))
    extractor = DatabricksMetricsExtractor(connection=connection, catalog=CATALOG)
    with pytest.raises(Exception):  # noqa: B017, PT011 - mapping covered above; assert cleanup here
        extractor.extract_metric_views(schema=SCHEMA)
    connection.cursor.return_value.close.assert_called_once()


def test_extractor_does_not_close_connection(metrics_extractor, mock_databricks_connection):
    """The extractor never closes the caller-owned connection."""
    metrics_extractor.extract_metric_views(schema=SCHEMA)
    mock_databricks_connection.close.assert_not_called()


# --- _parse_view_text (DESCRIBE … AS JSON -> YAML mapping) -------------------- #


def test_parse_view_text_extracts_yaml_mapping():
    """A json_metadata payload with a YAML view_text parses to a mapping."""
    parsed = _parse_view_text(describe_json(METRIC_VIEW_YAML))
    assert isinstance(parsed, dict)
    assert parsed["source"] == "main.sales.orders"


def test_parse_view_text_missing_view_text_returns_none():
    """A payload with no view_text field is not a usable definition."""
    assert _parse_view_text(describe_json(None)) is None


def test_parse_view_text_rejects_invalid_json():
    """Non-JSON input yields None."""
    assert _parse_view_text("not json {{{") is None


def test_parse_view_text_rejects_non_mapping_yaml():
    """A view_text that isn't a YAML mapping yields None."""
    assert _parse_view_text(describe_json("just a scalar string")) is None


def test_parse_view_text_handles_none_and_empty():
    """Null / blank / non-string payloads yield None."""
    assert _parse_view_text(None) is None
    assert _parse_view_text("") is None
    assert _parse_view_text(float("nan")) is None
