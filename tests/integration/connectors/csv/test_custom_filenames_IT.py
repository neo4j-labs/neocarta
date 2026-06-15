"""Test custom CSV filename functionality."""

from neocarta.connectors.csv import CSVConnector
from neocarta.enums import NodeLabel, RelationshipType


def test_custom_filename_in_constructor(neo4j_driver, temp_csv_dir):
    """Test that custom filenames specified in the constructor are used."""
    (temp_csv_dir / "custom_databases.csv").write_text("database_name\nmy-db\n")

    connector = CSVConnector(
        csv_directory=str(temp_csv_dir),
        neo4j_driver=neo4j_driver,
        database_name="neo4j",
        csv_file_map={NodeLabel.DATABASE: "custom_databases.csv"},
    )

    connector.ingest(include_nodes=[NodeLabel.DATABASE])

    with neo4j_driver.session(database="neo4j") as session:
        result = session.run("MATCH (d:Database) RETURN count(d) as count")
        assert result.single()["count"] == 1


def test_custom_filename_partial_override(neo4j_driver, temp_csv_dir):
    """Test that a partial csv_file_map overrides only the specified keys."""
    (temp_csv_dir / "alt_databases.csv").write_text("database_name\nmy-db\n")
    # schema uses the default filename
    (temp_csv_dir / "schema_info.csv").write_text("database_name,schema_name\nmy-db,my-schema\n")

    connector = CSVConnector(
        csv_directory=str(temp_csv_dir),
        neo4j_driver=neo4j_driver,
        database_name="neo4j",
        csv_file_map={NodeLabel.DATABASE: "alt_databases.csv"},
    )

    connector.ingest(
        include_nodes=[NodeLabel.DATABASE, NodeLabel.SCHEMA],
        include_relationships=[RelationshipType.HAS_SCHEMA],
    )

    with neo4j_driver.session(database="neo4j") as session:
        assert session.run("MATCH (d:Database) RETURN count(d) as count").single()["count"] == 1
        assert session.run("MATCH (s:Schema) RETURN count(s) as count").single()["count"] == 1
        assert (
            session.run("MATCH ()-[:HAS_SCHEMA]->() RETURN count(*) as count").single()["count"]
            == 1
        )
