"""Integration tests for the __neocarta_graph__ metadata node lifecycle."""

from neocarta import __version__
from neocarta.connectors.csv import CSVConnector
from neocarta.enums import NodeLabel


def _fetch_metadata_node(neo4j_driver) -> dict:
    with neo4j_driver.session(database="neo4j") as session:
        result = session.run(
            "MATCH (n:`__neocarta_graph__`) "
            "RETURN n.initial_version AS initial_version, "
            "       n.latest_version AS latest_version, "
            "       n.create_date AS create_date, "
            "       n.last_updated AS last_updated"
        )
        records = list(result)
    return records[0].data() if records else {}


def test_connector_run_creates_metadata_node(neo4j_driver, temp_csv_dir, sample_database_csv):
    """A connector run writes a singleton __neocarta_graph__ node stamped with the current version."""
    CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    ).run(include_nodes=[NodeLabel.DATABASE])

    with neo4j_driver.session(database="neo4j") as session:
        count = session.run("MATCH (n:`__neocarta_graph__`) RETURN count(n) AS c").single()["c"]
    assert count == 1

    record = _fetch_metadata_node(neo4j_driver)
    assert record["initial_version"] == __version__
    assert record["latest_version"] == __version__
    assert record["create_date"] is not None
    assert record["last_updated"] is not None


def test_connector_run_preserves_initial_version_on_subsequent_runs(
    neo4j_driver, temp_csv_dir, sample_database_csv
):
    """Re-running the connector updates latest_version/last_updated but keeps initial_version/create_date."""
    connector = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    connector.run(include_nodes=[NodeLabel.DATABASE])
    first = _fetch_metadata_node(neo4j_driver)

    # Override the version on the second run to simulate an upgraded connector.
    connector.loader.upsert_neocarta_graph_node(version="99.0.0")
    second = _fetch_metadata_node(neo4j_driver)

    assert second["initial_version"] == first["initial_version"]
    assert second["create_date"] == first["create_date"]
    assert second["latest_version"] == "99.0.0"
    assert second["last_updated"] >= first["last_updated"]
