"""Integration tests for the name range index created during ingestion."""

from neocarta.connectors.csv import CSVConnector
from neocarta.enums import NodeLabel


def _range_indexes(neo4j_driver) -> dict[str, dict]:
    """Return all RANGE node indexes keyed by index name."""
    with neo4j_driver.session(database="neo4j") as session:
        result = session.run(
            "SHOW INDEXES YIELD name, type, entityType, labelsOrTypes, properties "
            "WHERE type = 'RANGE' AND entityType = 'NODE' "
            "RETURN name, labelsOrTypes, properties"
        )
        records = list(result)
    return {r["name"]: r.data() for r in records}


def test_connector_run_creates_schema_name_range_index(
    neo4j_driver, temp_csv_dir, sample_database_csv, sample_schema_csv
):
    """A connector run creates a RANGE index on Schema.name backing MCP name lookups."""
    CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    ).run(include_nodes=[NodeLabel.DATABASE, NodeLabel.SCHEMA])

    indexes = _range_indexes(neo4j_driver)

    assert "schema_name_index" in indexes
    assert indexes["schema_name_index"]["labelsOrTypes"] == ["Schema"]
    assert indexes["schema_name_index"]["properties"] == ["name"]
