from unittest.mock import MagicMock

import pandas as pd
import pytest

from neocarta.connectors.snowflake.logs.extract import SnowflakeLogsExtractor
from neocarta.errors import ConfigError

DATABASE = "MYDB"
SCHEMA = "PUBLIC"


def _logs_connection(query_frame: pd.DataFrame) -> MagicMock:
    """A connection whose cursor returns ``query_frame`` from fetch_pandas_all."""
    connection = MagicMock()
    connection.cursor.return_value.fetch_pandas_all.return_value = query_frame
    return connection


def test_extractor_initialization():
    """The extractor stores its connection and database."""
    connection = MagicMock()
    extractor = SnowflakeLogsExtractor(connection=connection, database=DATABASE)
    assert extractor.database == DATABASE
    assert extractor.connection is connection


def test_extractor_folds_lowercase_database():
    """A lower-case database is resolved to Snowflake's stored (upper) case."""
    extractor = SnowflakeLogsExtractor(connection=MagicMock(), database="mydb")
    assert extractor.database == "MYDB"


@pytest.mark.parametrize("bad", [-1, True, 2.5, "10"])
def test_extract_query_logs_rejects_invalid_limit(bad):
    """A non-(plain-int) / negative limit is rejected with a ConfigError naming limit."""
    extractor = SnowflakeLogsExtractor(connection=MagicMock(), database=DATABASE)
    with pytest.raises(ConfigError, match="limit"):
        extractor.extract_query_logs(schema=SCHEMA, limit=bad, cache=False)


def test_extract_query_logs_calls_account_usage_query():
    """extract_query_logs queries ACCOUNT_USAGE.QUERY_HISTORY, scoped by database and schema."""
    frame = pd.DataFrame(
        {"query": ["SELECT customer_id FROM mydb.public.customers"], "error_result": [None]}
    )
    conn = _logs_connection(frame)
    extractor = SnowflakeLogsExtractor(connection=conn, database=DATABASE)
    extractor.extract_query_logs(
        schema=SCHEMA,
        start_timestamp="2024-01-01 00:00:00",
        end_timestamp="2024-01-31 23:59:59",
        limit=50,
        cache=False,
    )

    sql, params = conn.cursor.return_value.execute.call_args[0]
    assert "ACCOUNT_USAGE.QUERY_HISTORY" in sql
    assert "DATABASE_NAME = %(database)s" in sql
    assert "SCHEMA_NAME = %(schema)s" in sql
    assert "TO_TIMESTAMP_LTZ(%(start_timestamp)s)" in sql
    assert "LIMIT 50" in sql
    assert params["database"] == DATABASE
    assert params["schema"] == SCHEMA
    assert params["start_timestamp"] == "2024-01-01 00:00:00"


def test_extract_query_logs_default_timestamps_and_no_schema_filter():
    """Default timestamps use DATEADD, and no schema filter is emitted when schema is None."""
    conn = _logs_connection(pd.DataFrame({"query": [], "error_result": []}))
    extractor = SnowflakeLogsExtractor(connection=conn, database=DATABASE)
    extractor.extract_query_logs(cache=False)

    sql, params = conn.cursor.return_value.execute.call_args[0]
    assert "DATEADD('day', -30, CURRENT_TIMESTAMP())" in sql
    assert "SCHEMA_NAME" not in sql
    assert "schema" not in params


def test_extract_query_logs_parses_with_snowflake_dialect():
    """Parsed table_info carries the SNOWFLAKE platform/service (read='snowflake')."""
    frame = pd.DataFrame(
        {"query": ["SELECT customer_id FROM mydb.public.customers"], "error_result": [None]}
    )
    conn = _logs_connection(frame)
    extractor = SnowflakeLogsExtractor(connection=conn, database=DATABASE)
    extractor.extract_query_logs(schema=SCHEMA, cache=True)

    db_info = extractor.database_info
    assert not db_info.empty
    assert db_info.iloc[0]["platform"] == "SNOWFLAKE"
    assert db_info.iloc[0]["service"] == "SNOWFLAKE"
    assert "customers" in extractor.table_info["table_name"].unique()


def test_extract_query_logs_filters_failed_queries():
    """Failed queries (non-null error_result) are dropped when drop_failed_queries=True."""
    frame = pd.DataFrame(
        {
            "query": ["SELECT 1", "SELECT 2"],
            "error_result": [None, "0001"],
        }
    )
    conn = _logs_connection(frame)
    extractor = SnowflakeLogsExtractor(connection=conn, database=DATABASE)
    result = extractor.extract_query_logs(schema=SCHEMA, drop_failed_queries=True, cache=False)
    assert len(result) == 1
    assert result["error_result"].isnull().all()


def test_extract_query_logs_keeps_failed_queries_when_requested():
    """Failed queries are kept when drop_failed_queries=False."""
    frame = pd.DataFrame({"query": ["SELECT 1", "SELECT 2"], "error_result": [None, "0001"]})
    conn = _logs_connection(frame)
    extractor = SnowflakeLogsExtractor(connection=conn, database=DATABASE)
    result = extractor.extract_query_logs(schema=SCHEMA, drop_failed_queries=False, cache=False)
    assert len(result) == 2


def test_extract_query_logs_adds_query_id():
    """query_id is added as a SHA-256 hash of the query text."""
    frame = pd.DataFrame(
        {"query": ["SELECT customer_id FROM mydb.public.customers"], "error_result": [None]}
    )
    conn = _logs_connection(frame)
    extractor = SnowflakeLogsExtractor(connection=conn, database=DATABASE)
    result = extractor.extract_query_logs(schema=SCHEMA, cache=False)
    assert "query_id" in result.columns
    assert all(len(qid) == 64 for qid in result["query_id"])


def test_extract_with_empty_results():
    """No query history yields empty derived properties, no crash."""
    conn = _logs_connection(pd.DataFrame({"query": [], "error_result": []}))
    extractor = SnowflakeLogsExtractor(connection=conn, database=DATABASE)
    result = extractor.extract_query_logs(schema=SCHEMA, cache=True)
    assert result.empty
    assert extractor.database_info.empty
    assert extractor.schema_info.empty
    assert extractor.table_info.empty


def test_extract_query_logs_sql_filters_null_query_text():
    """The extraction SQL filters out NULL QUERY_TEXT rows server-side."""
    conn = _logs_connection(pd.DataFrame({"query": [], "error_result": []}))
    extractor = SnowflakeLogsExtractor(connection=conn, database=DATABASE)
    extractor.extract_query_logs(schema=SCHEMA, cache=False)
    sql = conn.cursor.return_value.execute.call_args[0][0]
    assert "QUERY_TEXT IS NOT NULL" in sql


def test_extract_query_logs_survives_null_query_text_row():
    """A retained row with NULL/blank QUERY_TEXT is dropped, not crashed on.

    ACCOUNT_USAGE.QUERY_TEXT is nullable (redacted / not-captured statements). A single
    such row must not abort the whole batch via create_query_id(None) -> AttributeError;
    the valid queries alongside it must still be processed.
    """
    frame = pd.DataFrame(
        {
            "query": [None, "", "SELECT id FROM mydb.public.orders"],
            "error_result": [None, None, None],
        }
    )
    conn = _logs_connection(frame)
    extractor = SnowflakeLogsExtractor(connection=conn, database=DATABASE)
    # drop_failed_queries=False keeps all rows so the NULL/blank ones reach the guard.
    result = extractor.extract_query_logs(schema=SCHEMA, drop_failed_queries=False, cache=True)
    assert len(result) == 1  # only the real query survives the null/blank guard
    assert "query_id" in result.columns
    assert "orders" in extractor.table_info["table_name"].unique()
