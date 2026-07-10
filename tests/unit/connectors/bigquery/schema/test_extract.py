import pandas as pd

from neocarta.connectors.bigquery.schema.extract import BigQuerySchemaExtractor


def test_get_database_info(bigquery_extractor_with_cache: BigQuerySchemaExtractor):
    """Test database_info property returns cached data."""
    assert bigquery_extractor_with_cache.database_info.shape[0] == 1
    assert bigquery_extractor_with_cache.database_info.iloc[0]["project_id"] == "test-project-id"


def test_get_schema_info(bigquery_extractor_with_cache: BigQuerySchemaExtractor):
    """Test schema_info property returns cached data."""
    assert bigquery_extractor_with_cache.schema_info.shape[0] == 1
    assert bigquery_extractor_with_cache.schema_info.iloc[0]["dataset_id"] == "test_dataset"


def test_get_table_info(bigquery_extractor_with_cache: BigQuerySchemaExtractor):
    """Test table_info property returns cached data."""
    assert bigquery_extractor_with_cache.table_info.shape[0] == 2
    assert bigquery_extractor_with_cache.table_info.iloc[0]["table_name"] == "customers"
    assert bigquery_extractor_with_cache.table_info.iloc[1]["table_name"] == "orders"


def test_get_column_info(bigquery_extractor_with_cache: BigQuerySchemaExtractor):
    """Test column_info property returns cached data."""
    assert bigquery_extractor_with_cache.column_info.shape[0] == 4
    assert bigquery_extractor_with_cache.column_info.iloc[0]["column_name"] == "customer_id"


def test_get_column_references_info(bigquery_extractor_with_cache: BigQuerySchemaExtractor):
    """Test column_references_info property returns cached data."""
    assert bigquery_extractor_with_cache.column_references_info.shape[0] == 1
    assert bigquery_extractor_with_cache.column_references_info.iloc[0]["table_name"] == "orders"


def test_get_column_unique_values(bigquery_extractor_with_cache: BigQuerySchemaExtractor):
    """Test column_unique_values property returns cached data."""
    assert bigquery_extractor_with_cache.column_unique_values.shape[0] == 2
    assert (
        bigquery_extractor_with_cache.column_unique_values.iloc[0]["column_name"] == "customer_id"
    )


def test_extract_column_unique_values_includes_name_parts(
    mock_bigquery_client, bigquery_extractor: BigQuerySchemaExtractor
):
    """Sampled-value rows carry the table's project_id/dataset_id/table_name name-parts."""
    mock_bigquery_client.query.return_value.to_dataframe.return_value = pd.DataFrame(
        [{"customer_id": ["1", "2"]}]
    )

    result = bigquery_extractor.extract_column_unique_values_for_table(
        "customers", ["customer_id"], dataset_id="test_dataset", cache=False, column_info=None
    )

    assert list(result["unique_value"]) == ["1", "2"]
    assert list(result["project_id"]) == ["test-project-id", "test-project-id"]
    assert list(result["dataset_id"]) == ["test_dataset", "test_dataset"]
    assert list(result["table_name"]) == ["customers", "customers"]


def test_extract_column_unique_values_all_complex_types_early_return(
    mock_bigquery_client, bigquery_extractor: BigQuerySchemaExtractor
):
    """When every column is a complex type, return an empty frame (with name-parts) and no query."""
    bigquery_extractor._cache["column_info"] = pd.DataFrame(
        [{"table_name": "customers", "column_name": "payload", "data_type": "ARRAY<INT64>"}]
    )

    result = bigquery_extractor.extract_column_unique_values_for_table(
        "customers", ["payload"], dataset_id="test_dataset", cache=False
    )

    assert result.empty
    assert list(result.columns) == [
        "column_name",
        "unique_value",
        "column_id",
        "value_id",
        "project_id",
        "dataset_id",
        "table_name",
    ]
    mock_bigquery_client.query.assert_not_called()
