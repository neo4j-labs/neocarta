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
