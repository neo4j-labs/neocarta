import pytest

from neocarta.connectors.bigquery.schema.extract import BigQuerySchemaExtractor
from tests.support.characterization.bigquery_cache import (
    make_mock_bigquery_client,
    seed_bigquery_schema_cache,
)


@pytest.fixture
def mock_bigquery_client():
    """Create a mock BigQuery client."""
    return make_mock_bigquery_client()


@pytest.fixture
def bigquery_extractor(mock_bigquery_client):
    """Create a BigQuerySchemaExtractor with a mocked client."""
    return BigQuerySchemaExtractor(client=mock_bigquery_client, dataset_id="test_dataset")


@pytest.fixture
def bigquery_extractor_with_cache(mock_bigquery_client):
    """Create a BigQuerySchemaExtractor with the shared customers/orders cache pre-populated."""
    extractor = BigQuerySchemaExtractor(client=mock_bigquery_client, dataset_id="test_dataset")
    return seed_bigquery_schema_cache(extractor)
