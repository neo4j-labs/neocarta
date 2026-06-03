from unittest.mock import MagicMock, Mock

import pandas as pd
import pytest

from neocarta.connectors.bigquery.logs.extract import BigQueryLogsExtractor


@pytest.fixture
def mock_bigquery_client():
    """Create a mock BigQuery client."""
    client = Mock()
    client.project = "test-project-id"
    return client


@pytest.fixture
def mock_query_logs_response():
    """Create mock query log data that would be returned from JOBS_BY_PROJECT."""
    return pd.DataFrame(
        [
            {
                "creation_time": pd.Timestamp("2024-01-01 10:00:00"),
                "end_time": pd.Timestamp("2024-01-01 10:00:05"),
                "duration_seconds": 5,
                "job_id": "job_123",
                "state": "DONE",
                "statement_type": "SELECT",
                "total_bytes_processed": 1024,
                "total_slot_ms": 500,
                "error_result": None,
                "query": "SELECT customer_id, customer_name FROM `test-project-id.test_dataset.customers` WHERE customer_id = 1",
            },
            {
                "creation_time": pd.Timestamp("2024-01-01 10:05:00"),
                "end_time": pd.Timestamp("2024-01-01 10:05:03"),
                "duration_seconds": 3,
                "job_id": "job_456",
                "state": "DONE",
                "statement_type": "SELECT",
                "total_bytes_processed": 2048,
                "total_slot_ms": 300,
                "error_result": None,
                "query": """
                SELECT o.order_id, c.customer_name
                FROM `test-project-id.test_dataset.orders` o
                JOIN `test-project-id.test_dataset.customers` c
                ON o.customer_id = c.customer_id
            """,
            },
            {
                "creation_time": pd.Timestamp("2024-01-01 10:10:00"),
                "end_time": pd.Timestamp("2024-01-01 10:10:01"),
                "duration_seconds": 1,
                "job_id": "job_789",
                "state": "DONE",
                "statement_type": "SELECT",
                "total_bytes_processed": 512,
                "total_slot_ms": 100,
                "error_result": {"reason": "invalidQuery", "message": "Syntax error"},
                "query": "SELECT * FROM invalid_table",
            },
        ]
    )


@pytest.fixture
def mock_bq_logs_extractor(mock_bigquery_client, mock_query_logs_response):
    """Create a BigQueryLogsExtractor with mocked query responses."""
    extractor = BigQueryLogsExtractor(client=mock_bigquery_client)

    # Mock the client.query() method to return our test data
    mock_query_result = MagicMock()
    mock_query_result.to_dataframe.return_value = mock_query_logs_response
    mock_bigquery_client.query.return_value = mock_query_result

    return extractor


@pytest.fixture
def bq_logs_extractor_with_cache(mock_bq_logs_extractor):
    """Create a BigQueryLogsExtractor with pre-populated cache after extraction."""
    # Run extraction to populate cache
    mock_bq_logs_extractor.extract_query_logs(
        dataset_id="test_dataset",
        region="region-us",
        limit=100,
        drop_failed_queries=True,
        cache=True,
    )

    return mock_bq_logs_extractor
