"""Integration tests for SalesforceConnector.

Runs against a real Neo4j instance when NEO4J_URI is set; falls back to
testcontainers otherwise.  All data is synthetic.
"""

import pytest

from neocarta.connectors.salesforce import SalesforceConnector

from .conftest import _TEST_DB, ORG_NAME

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def clean_db(neo4j_driver):
    """Wipe the test database before each individual test."""
    with neo4j_driver.session(database=_TEST_DB) as s:
        s.run("MATCH (n) DETACH DELETE n")


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _query(driver, cypher: str, **params) -> list[dict]:
    records, _, _ = driver.execute_query(cypher, parameters_=params, database_="neo4j")
    return [r.data() for r in records]


def _count(driver, label: str) -> int:
    rows = _query(driver, f"MATCH (n:{label}) RETURN count(n) AS c")
    return rows[0]["c"]


# ─── Tests ───────────────────────────────────────────────────────────────────


class TestSalesforceConnectorIT:
    """Full ETL round-trip against a containerised Neo4j instance."""

    def test_run_creates_database_node(self, neo4j_driver, sample_objects):
        connector = SalesforceConnector(sample_objects, ORG_NAME, neo4j_driver)
        connector.run()
        assert _count(neo4j_driver, "Database") == 1
        rows = _query(
            neo4j_driver, "MATCH (d:Database) RETURN d.name AS name, d.platform AS platform"
        )
        assert rows[0]["name"] == ORG_NAME
        assert rows[0]["platform"].upper() == "SALESFORCE"

    def test_run_creates_schema_nodes(self, neo4j_driver, sample_objects):
        connector = SalesforceConnector(sample_objects, ORG_NAME, neo4j_driver)
        connector.run()
        # Account + Contact → core; Acme__Widget__c → acme
        assert _count(neo4j_driver, "Schema") == 2
        names = {r["name"] for r in _query(neo4j_driver, "MATCH (s:Schema) RETURN s.name AS name")}
        assert names == {"core", "acme"}

    def test_run_creates_table_nodes(self, neo4j_driver, sample_objects):
        connector = SalesforceConnector(sample_objects, ORG_NAME, neo4j_driver)
        connector.run()
        assert _count(neo4j_driver, "Table") == 3

    def test_run_creates_column_nodes(self, neo4j_driver, sample_objects):
        connector = SalesforceConnector(sample_objects, ORG_NAME, neo4j_driver)
        connector.run()
        # Account: 3 fields, Contact: 3 fields, Widget: 1 field = 7
        assert _count(neo4j_driver, "Column") >= 7

    def test_hierarchy_relationships(self, neo4j_driver, sample_objects):
        connector = SalesforceConnector(sample_objects, ORG_NAME, neo4j_driver)
        connector.run()

        has_schema = _query(
            neo4j_driver,
            "MATCH (:Database)-[:HAS_SCHEMA]->(:Schema) RETURN count(*) AS c",
        )
        assert has_schema[0]["c"] == 2

        has_table = _query(
            neo4j_driver,
            "MATCH (:Schema)-[:HAS_TABLE]->(:Table) RETURN count(*) AS c",
        )
        assert has_table[0]["c"] == 3

        has_column = _query(
            neo4j_driver,
            "MATCH (:Table)-[:HAS_COLUMN]->(:Column) RETURN count(*) AS c",
        )
        assert has_column[0]["c"] >= 7

    def test_references_relationship_known_target(self, neo4j_driver, sample_objects):
        connector = SalesforceConnector(sample_objects, ORG_NAME, neo4j_driver)
        connector.run()

        # contact.accountid → account.id must exist as REFERENCES
        rows = _query(
            neo4j_driver,
            """
            MATCH (src:Column)-[:REFERENCES]->(tgt:Column)
            WHERE src.id ENDS WITH '.accountid'
            RETURN tgt.id AS tgt_id
            """,
        )
        assert len(rows) == 1
        assert rows[0]["tgt_id"].endswith(".account.id")

    def test_references_stub_for_unknown_target(self, neo4j_driver, sample_objects):
        connector = SalesforceConnector(sample_objects, ORG_NAME, neo4j_driver)
        connector.run()

        # contact.ownerid → user.id; "User" is not in described set → stub Column
        rows = _query(
            neo4j_driver,
            """
            MATCH (src:Column)-[:REFERENCES]->(tgt:Column)
            WHERE src.id ENDS WITH '.ownerid'
            RETURN tgt.id AS tgt_id
            """,
        )
        assert len(rows) == 1
        # Stub exists — it has an id but no name/label (set only via MERGE)
        stub_id = rows[0]["tgt_id"]
        assert "user" in stub_id

    def test_sfdc_table_properties_set(self, neo4j_driver, sample_objects):
        connector = SalesforceConnector(sample_objects, ORG_NAME, neo4j_driver)
        connector.run()

        rows = _query(
            neo4j_driver,
            """
            MATCH (t:Table {name: 'account'})
            RETURN t.label AS label, t.labelPlural AS labelPlural,
                   t.keyPrefix AS keyPrefix, t.isCustom AS isCustom,
                   t.namespace AS namespace
            """,
        )
        assert len(rows) == 1
        r = rows[0]
        assert r["label"] == "Account"
        assert r["labelPlural"] == "Accounts"
        assert r["keyPrefix"] == "001"
        assert r["isCustom"] is False
        assert r["namespace"] == "core"

    def test_sfdc_column_properties_set(self, neo4j_driver, sample_objects):
        connector = SalesforceConnector(sample_objects, ORG_NAME, neo4j_driver)
        connector.run()

        rows = _query(
            neo4j_driver,
            """
            MATCH (c:Column)
            WHERE c.id ENDS WITH '.account.type'
            RETURN c.label AS label, c.picklistValues AS picklistValues
            """,
        )
        assert len(rows) == 1
        r = rows[0]
        assert r["label"] == "Account Type"
        assert set(r["picklistValues"]) == {"Customer", "Partner"}

    def test_idempotent_run(self, neo4j_driver, sample_objects):
        """Running the connector twice must not create duplicate nodes."""
        connector1 = SalesforceConnector(sample_objects, ORG_NAME, neo4j_driver)
        connector1.run()
        tables_first = _count(neo4j_driver, "Table")
        columns_first = _count(neo4j_driver, "Column")

        connector2 = SalesforceConnector(sample_objects, ORG_NAME, neo4j_driver)
        connector2.run()
        assert _count(neo4j_driver, "Table") == tables_first
        assert _count(neo4j_driver, "Column") == columns_first

    def test_csv_output_written(self, neo4j_driver, sample_objects, tmp_path):
        connector = SalesforceConnector(sample_objects, ORG_NAME, neo4j_driver, output_dir=tmp_path)
        connector.run()
        assert (tmp_path / "database_info.csv").exists()
        assert (tmp_path / "schema_info.csv").exists()
        assert (tmp_path / "table_info.csv").exists()
        assert (tmp_path / "column_info.csv").exists()
        assert (tmp_path / "column_references_info.csv").exists()
