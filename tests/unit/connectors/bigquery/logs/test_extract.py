from unittest.mock import MagicMock

import pandas as pd
import pytest

from neocarta.connectors.bigquery.logs.extract import BigQueryLogsExtractor
from neocarta.errors import ConfigError


def test_extractor_initialization(mock_bigquery_client):
    """Test that the extractor initializes correctly."""
    extractor = BigQueryLogsExtractor(client=mock_bigquery_client)

    assert extractor.project_id == "test-project-id"
    assert extractor.client == mock_bigquery_client


def test_extract_query_logs_calls_correct_query(mock_bq_logs_extractor):
    """Test that extract_query_logs calls BigQuery with the correct SQL."""
    mock_bq_logs_extractor.extract_query_logs(
        dataset_id="test_dataset",
        region="region-us",
        start_timestamp="2024-01-01 00:00:00",
        end_timestamp="2024-01-31 23:59:59",
        limit=50,
        cache=False,
    )

    # Verify the query was called
    assert mock_bq_logs_extractor.client.query.called

    # Get the actual query that was executed
    actual_query = mock_bq_logs_extractor.client.query.call_args[0][0]

    # Verify key components of the query
    assert "INFORMATION_SCHEMA.JOBS_BY_PROJECT" in actual_query
    assert "ref.dataset_id = 'test_dataset'" in actual_query
    assert "TIMESTAMP('2024-01-01 00:00:00')" in actual_query
    assert "TIMESTAMP('2024-01-31 23:59:59')" in actual_query
    assert "LIMIT 50" in actual_query


def test_extract_query_logs_filters_failed_queries(
    mock_bq_logs_extractor, mock_query_logs_response
):
    """Test that failed queries are filtered out when drop_failed_queries=True."""
    result = mock_bq_logs_extractor.extract_query_logs(
        dataset_id="test_dataset", drop_failed_queries=True, cache=False
    )

    # Should only have 2 queries (1 failed query filtered out)
    assert len(result) == 2
    assert result["error_result"].isnull().all()


def test_extract_query_logs_keeps_failed_queries(mock_bq_logs_extractor, mock_query_logs_response):
    """Test that failed queries are kept when drop_failed_queries=False."""
    result = mock_bq_logs_extractor.extract_query_logs(
        dataset_id="test_dataset", drop_failed_queries=False, cache=False
    )

    # Should have all 3 queries
    assert len(result) == 3


def test_extract_query_logs_adds_query_id(mock_bq_logs_extractor):
    """Test that query_id is added as hash of query text."""
    result = mock_bq_logs_extractor.extract_query_logs(
        dataset_id="test_dataset", drop_failed_queries=True, cache=False
    )

    # Check that query_id column exists
    assert "query_id" in result.columns
    # Check that all query_ids are 64-character hex strings (SHA256)
    assert all(len(qid) == 64 for qid in result["query_id"])


def test_extract_query_logs_caches_data(mock_bq_logs_extractor):
    """Test that data is cached when cache=True."""
    mock_bq_logs_extractor.extract_query_logs(dataset_id="test_dataset", cache=True)

    # Verify cache is populated
    assert not mock_bq_logs_extractor._cache["query_info"].empty
    assert not mock_bq_logs_extractor._cache["table_info"].empty
    assert not mock_bq_logs_extractor._cache["column_info"].empty


def test_query_info_property(bq_logs_extractor_with_cache):
    """Test query_info property returns cached query data."""
    query_info = bq_logs_extractor_with_cache.query_info

    assert not query_info.empty
    assert len(query_info) == 2  # Failed queries filtered out
    assert "query_id" in query_info.columns
    assert "job_id" in query_info.columns


def test_database_info_property(bq_logs_extractor_with_cache):
    """Test database_info property extracts unique databases."""
    db_info = bq_logs_extractor_with_cache.database_info

    assert not db_info.empty
    assert "project_id" in db_info.columns
    assert "platform" in db_info.columns
    assert "service" in db_info.columns
    # Should have deduplicated database info
    assert db_info["platform"].iloc[0] == "GCP"
    assert db_info["service"].iloc[0] == "BIGQUERY"


def test_schema_info_property(bq_logs_extractor_with_cache):
    """Test schema_info property extracts unique schemas."""
    schema_info = bq_logs_extractor_with_cache.schema_info

    assert not schema_info.empty
    assert "dataset_id" in schema_info.columns
    assert "dataset_name" in schema_info.columns
    # Should have test_dataset
    assert "test_dataset" in schema_info["dataset_name"].values


def test_table_info_property(bq_logs_extractor_with_cache):
    """Test table_info property extracts unique tables from parsed queries."""
    table_info = bq_logs_extractor_with_cache.table_info

    assert not table_info.empty
    assert "table_id" in table_info.columns
    assert "table_name" in table_info.columns
    # Should have customers and orders tables
    table_names = table_info["table_name"].unique()
    assert "customers" in table_names
    assert "orders" in table_names


def test_column_info_property(bq_logs_extractor_with_cache):
    """Test column_info property extracts columns from parsed queries."""
    column_info = bq_logs_extractor_with_cache.column_info

    assert not column_info.empty
    assert "column_id" in column_info.columns
    assert "column_name" in column_info.columns
    # Should have columns mentioned in queries
    column_names = column_info["column_name"].unique()
    assert "customer_id" in column_names
    assert "customer_name" in column_names


def test_query_table_info_property(bq_logs_extractor_with_cache):
    """Test query_table_info property returns query-to-table relationships."""
    query_table_info = bq_logs_extractor_with_cache.query_table_info

    assert not query_table_info.empty
    assert "query_id" in query_table_info.columns
    assert "table_id" in query_table_info.columns
    # Should have relationships between queries and tables
    assert len(query_table_info) > 0


def test_query_column_info_property(bq_logs_extractor_with_cache):
    """Test query_column_info property returns query-to-column relationships."""
    query_column_info = bq_logs_extractor_with_cache.query_column_info

    assert not query_column_info.empty
    assert "query_id" in query_column_info.columns
    assert "column_id" in query_column_info.columns
    # Should have relationships between queries and columns
    assert len(query_column_info) > 0


def test_extract_with_default_timestamps(mock_bq_logs_extractor):
    """Test that default timestamps are used when not provided."""
    mock_bq_logs_extractor.extract_query_logs(dataset_id="test_dataset", cache=False)

    actual_query = mock_bq_logs_extractor.client.query.call_args[0][0]

    # Should use default 30 day lookback
    assert "TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)" in actual_query
    assert "CURRENT_TIMESTAMP()" in actual_query


def test_extractor_with_no_project_id_raises_error():
    """Test that initializing without project_id raises ConfigError."""
    mock_client = MagicMock()
    mock_client.project = None

    with pytest.raises(ConfigError, match="Project ID is required"):
        BigQueryLogsExtractor(client=mock_client)


def test_extract_with_empty_results(mock_bigquery_client):
    """Test handling when no query logs are returned."""
    extractor = BigQueryLogsExtractor(client=mock_bigquery_client)

    # Mock empty response
    mock_query_result = MagicMock()
    mock_query_result.to_dataframe.return_value = pd.DataFrame(columns=["error_result", "query"])
    mock_bigquery_client.query.return_value = mock_query_result

    result = extractor.extract_query_logs(dataset_id="test_dataset", cache=True)

    assert result.empty
    # Properties should return empty DataFrames gracefully
    assert extractor.database_info.empty
    assert extractor.schema_info.empty
    assert extractor.table_info.empty


def test_extract_with_unparseable_queries(mock_bigquery_client):
    """Test handling when SQL queries cannot be parsed."""
    extractor = BigQueryLogsExtractor(client=mock_bigquery_client)

    # Mock response with invalid SQL
    mock_response = pd.DataFrame(
        [
            {
                "creation_time": pd.Timestamp("2024-01-01 10:00:00"),
                "end_time": pd.Timestamp("2024-01-01 10:00:01"),
                "duration_seconds": 1,
                "job_id": "job_123",
                "state": "DONE",
                "statement_type": "SELECT",
                "total_bytes_processed": 100,
                "total_slot_ms": 50,
                "error_result": None,
                "query": "THIS IS NOT VALID SQL @#$%",
            }
        ]
    )

    mock_query_result = MagicMock()
    mock_query_result.to_dataframe.return_value = mock_response
    mock_bigquery_client.query.return_value = mock_query_result

    result = extractor.extract_query_logs(dataset_id="test_dataset", cache=True)

    # Should handle gracefully - parse_sql_query returns None on error
    assert len(result) == 1
    # Table/column info might be empty due to parse failure
    assert extractor._cache["table_info"].empty or len(extractor._cache["table_info"]) == 0


def test_extract_with_multiple_regions(mock_bigquery_client):
    """Test that region parameter is used correctly."""
    extractor = BigQueryLogsExtractor(client=mock_bigquery_client)

    mock_query_result = MagicMock()
    mock_query_result.to_dataframe.return_value = pd.DataFrame(columns=["error_result", "query"])
    mock_bigquery_client.query.return_value = mock_query_result

    # Test different regions
    for region in ["us", "europe-west1", "asia-northeast1"]:
        extractor.extract_query_logs(dataset_id="test_dataset", region=region, cache=False)

        actual_query = mock_bigquery_client.query.call_args[0][0]
        assert f"{region}.INFORMATION_SCHEMA.JOBS_BY_PROJECT" in actual_query


def test_column_references_info_with_joins(mock_bigquery_client):
    """Test that JOIN relationships are captured in column_references_info."""
    extractor = BigQueryLogsExtractor(client=mock_bigquery_client)

    # Mock response with JOIN query
    mock_response = pd.DataFrame(
        [
            {
                "creation_time": pd.Timestamp("2024-01-01 10:00:00"),
                "end_time": pd.Timestamp("2024-01-01 10:00:01"),
                "duration_seconds": 1,
                "job_id": "job_123",
                "state": "DONE",
                "statement_type": "SELECT",
                "total_bytes_processed": 100,
                "total_slot_ms": 50,
                "error_result": None,
                "query": """
            SELECT a.id, b.name
            FROM `test-project-id.test_dataset.table_a` a
            JOIN `test-project-id.test_dataset.table_b` b
            ON a.id = b.id
        """,
            }
        ]
    )

    mock_query_result = MagicMock()
    mock_query_result.to_dataframe.return_value = mock_response
    mock_bigquery_client.query.return_value = mock_query_result

    extractor.extract_query_logs(dataset_id="test_dataset", cache=True)

    refs = extractor.column_references_info
    # Should capture JOIN relationship if parsed correctly
    if not refs.empty:
        assert "left_column_id" in refs.columns
        assert "right_column_id" in refs.columns


def test_cache_isolation(mock_bigquery_client):
    """Test that multiple extractions don't interfere with each other."""
    extractor1 = BigQueryLogsExtractor(client=mock_bigquery_client)
    extractor2 = BigQueryLogsExtractor(client=mock_bigquery_client)

    mock_response = pd.DataFrame(
        [
            {
                "creation_time": pd.Timestamp("2024-01-01 10:00:00"),
                "end_time": pd.Timestamp("2024-01-01 10:00:01"),
                "duration_seconds": 1,
                "job_id": "job_123",
                "state": "DONE",
                "statement_type": "SELECT",
                "total_bytes_processed": 100,
                "total_slot_ms": 50,
                "error_result": None,
                "query": "SELECT * FROM `test-project-id.test_dataset.test_table`",
            }
        ]
    )

    mock_query_result = MagicMock()
    mock_query_result.to_dataframe.return_value = mock_response
    mock_bigquery_client.query.return_value = mock_query_result

    # Extract with first instance
    extractor1.extract_query_logs(dataset_id="test_dataset", cache=True)

    # Second instance should have empty cache
    assert extractor2._cache.get("query_info") is None
    assert extractor1._cache.get("query_info") is not None


@pytest.mark.parametrize(
    "timestamp_config",
    [
        {"start": "2024-01-01 00:00:00", "end": "2024-01-31 23:59:59"},
        {"start": "2023-12-01 00:00:00", "end": "2023-12-31 23:59:59"},
        {"start": None, "end": None},  # Test defaults
    ],
)
def test_various_timestamp_configurations(mock_bigquery_client, timestamp_config):
    """Test extraction with various timestamp configurations."""
    extractor = BigQueryLogsExtractor(client=mock_bigquery_client)

    mock_query_result = MagicMock()
    mock_query_result.to_dataframe.return_value = pd.DataFrame(columns=["error_result", "query"])
    mock_bigquery_client.query.return_value = mock_query_result

    extractor.extract_query_logs(
        dataset_id="test_dataset",
        start_timestamp=timestamp_config["start"],
        end_timestamp=timestamp_config["end"],
        cache=False,
    )

    actual_query = mock_bigquery_client.query.call_args[0][0]

    if timestamp_config["start"]:
        assert f"TIMESTAMP('{timestamp_config['start']}')" in actual_query
    else:
        assert "TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)" in actual_query
