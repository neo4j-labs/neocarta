from neocarta.connectors.query_log.extract import QueryLogExtractor


def test_extract_info_from_query_log_json_bigquery(query_log_extractor: QueryLogExtractor):
    query_log_file = "tests/unit/connectors/query_log/test_bigquery_query_log.json"
    query_log_extractor.extract_info_from_query_log_json(
        query_log_file, source="bigquery", cache=True
    )
    assert query_log_extractor.query_info.shape[0] == 1
    assert query_log_extractor.database_info.shape[0] == 1
    assert query_log_extractor.schema_info.shape[0] == 1
    assert query_log_extractor.table_info.shape[0] == 3
    assert query_log_extractor.column_info.shape[0] == 8
    assert query_log_extractor.column_references_info.shape[0] == 2
