"""Integration tests for CSV connector workflow."""

from neocarta.connectors.csv import CSVConnector
from neocarta.enums import NodeLabel, RelationshipType


def test_run_workflow_loads_all_nodes(neo4j_driver, temp_csv_dir, all_sample_csvs):
    """Test that running the complete workflow loads all node types."""
    # all_sample_csvs ensures all CSV fixtures are created
    workflow = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    workflow.ingest()

    with neo4j_driver.session(database="neo4j") as session:
        # Verify Database node
        result = session.run(
            "MATCH (d:Database {id: 'my_project'}) RETURN d.name as name, d.platform as platform"
        )
        record = result.single()
        assert record is not None
        assert record["name"] == "my-project"
        assert record["platform"] == "GCP"

        # Verify Schema nodes
        result = session.run("MATCH (s:Schema) RETURN count(s) as count")
        assert result.single()["count"] == 2

        # Verify specific schemas exist
        result = session.run("MATCH (s:Schema) RETURN s.name as name ORDER BY name")
        schema_names = [record["name"] for record in result]
        assert "analytics" in schema_names
        assert "sales" in schema_names

        # Verify Table nodes
        result = session.run("MATCH (t:Table) RETURN count(t) as count")
        assert result.single()["count"] == 3

        # Verify specific tables exist
        result = session.run("MATCH (t:Table) RETURN t.name as name ORDER BY name")
        table_names = [record["name"] for record in result]
        assert "customers" in table_names
        assert "orders" in table_names
        assert "summary" in table_names

        # Verify Column nodes
        result = session.run("MATCH (c:Column) RETURN count(c) as count")
        assert result.single()["count"] == 5

        # Verify Value nodes
        result = session.run("MATCH (v:Value) RETURN count(v) as count")
        assert result.single()["count"] == 3

        # Verify Query nodes
        result = session.run("MATCH (q:Query) RETURN count(q) as count")
        assert result.single()["count"] == 2

        # Verify Glossary node
        result = session.run("MATCH (g:Glossary {id: 'sales_glossary'}) RETURN g.name as name")
        record = result.single()
        assert record is not None
        assert record["name"] == "Sales Glossary"

        # Verify Category nodes
        result = session.run("MATCH (c:Category) RETURN count(c) as count")
        assert result.single()["count"] == 1

        # Verify BusinessTerm nodes
        result = session.run("MATCH (bt:BusinessTerm) RETURN count(bt) as count")
        assert result.single()["count"] == 1


def test_run_workflow_loads_all_relationships(neo4j_driver, temp_csv_dir, all_sample_csvs):
    """Test that running the complete workflow loads all relationship types."""
    workflow = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    workflow.ingest()

    with neo4j_driver.session(database="neo4j") as session:
        # Verify HAS_SCHEMA relationship
        result = session.run("MATCH ()-[r:HAS_SCHEMA]->() RETURN count(r) as count")
        assert result.single()["count"] == 2

        # Verify HAS_TABLE relationships
        result = session.run("MATCH ()-[r:HAS_TABLE]->() RETURN count(r) as count")
        assert result.single()["count"] == 3

        # Verify HAS_COLUMN relationships
        result = session.run("MATCH ()-[r:HAS_COLUMN]->() RETURN count(r) as count")
        assert result.single()["count"] == 5

        # Verify REFERENCES relationships (foreign keys)
        result = session.run("MATCH ()-[r:REFERENCES]->() RETURN count(r) as count")
        assert result.single()["count"] == 1

        # Verify specific foreign key exists
        result = session.run("""
            MATCH (source:Column {name: 'customer_id'})<-[:HAS_COLUMN]-(t:Table {name: 'orders'})
            MATCH (source)-[r:REFERENCES]->(target:Column {name: 'customer_id'})<-[:HAS_COLUMN]-(t2:Table {name: 'customers'})
            RETURN r.criteria as criteria
        """)
        record = result.single()
        assert record is not None
        assert record["criteria"] == "orders.customer_id = customers.customer_id"

        # Verify HAS_VALUE relationships
        result = session.run("MATCH ()-[r:HAS_VALUE]->() RETURN count(r) as count")
        assert result.single()["count"] == 3

        # Verify USES_TABLE relationships
        result = session.run("MATCH ()-[r:USES_TABLE]->() RETURN count(r) as count")
        assert result.single()["count"] == 2

        # Verify USES_COLUMN relationships
        result = session.run("MATCH ()-[r:USES_COLUMN]->() RETURN count(r) as count")
        assert result.single()["count"] == 2

        # Verify HAS_CATEGORY relationships
        result = session.run("MATCH ()-[r:HAS_CATEGORY]->() RETURN count(r) as count")
        assert result.single()["count"] == 1

        # Verify HAS_BUSINESS_TERM relationships
        result = session.run("MATCH ()-[r:HAS_BUSINESS_TERM]->() RETURN count(r) as count")
        assert result.single()["count"] == 1


def test_include_nodes_core_only(neo4j_driver, temp_csv_dir, all_sample_csvs):
    """Test include_nodes parameter to load only core schema entities."""
    workflow = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    # Load only core entities
    workflow.ingest(
        include_nodes=[NodeLabel.DATABASE, NodeLabel.SCHEMA, NodeLabel.TABLE, NodeLabel.COLUMN],
        include_relationships=[
            RelationshipType.HAS_SCHEMA,
            RelationshipType.HAS_TABLE,
            RelationshipType.HAS_COLUMN,
            RelationshipType.REFERENCES,
        ],
    )

    with neo4j_driver.session(database="neo4j") as session:
        # Should have core nodes
        result = session.run("MATCH (d:Database) RETURN count(d) as count")
        assert result.single()["count"] == 1

        result = session.run("MATCH (s:Schema) RETURN count(s) as count")
        assert result.single()["count"] == 2

        result = session.run("MATCH (t:Table) RETURN count(t) as count")
        assert result.single()["count"] == 3

        result = session.run("MATCH (c:Column) RETURN count(c) as count")
        assert result.single()["count"] == 5

        # Should NOT have extended nodes
        result = session.run("MATCH (v:Value) RETURN count(v) as count")
        assert result.single()["count"] == 0

        result = session.run("MATCH (q:Query) RETURN count(q) as count")
        assert result.single()["count"] == 0

        result = session.run("MATCH (g:Glossary) RETURN count(g) as count")
        assert result.single()["count"] == 0

        # Should have core relationships
        result = session.run("MATCH ()-[r:HAS_SCHEMA]->() RETURN count(r) as count")
        assert result.single()["count"] == 2

        result = session.run("MATCH ()-[r:REFERENCES]->() RETURN count(r) as count")
        assert result.single()["count"] == 1

        # Should NOT have extended relationships
        result = session.run("MATCH ()-[r:USES_TABLE]->() RETURN count(r) as count")
        assert result.single()["count"] == 0


def test_include_nodes_queries_only(neo4j_driver, temp_csv_dir, all_sample_csvs):
    """Test include_nodes parameter to load only queries and their lineage."""
    workflow = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    # Load queries and their target nodes (tables/columns) for lineage relationships
    workflow.ingest(
        include_nodes=[NodeLabel.QUERY, NodeLabel.TABLE, NodeLabel.COLUMN],
        include_relationships=[RelationshipType.USES_TABLE, RelationshipType.USES_COLUMN],
    )

    with neo4j_driver.session(database="neo4j") as session:
        # Should have queries
        result = session.run("MATCH (q:Query) RETURN count(q) as count")
        assert result.single()["count"] == 2

        # Should have query lineage relationships
        result = session.run("MATCH ()-[r:USES_TABLE]->() RETURN count(r) as count")
        assert result.single()["count"] == 2

        result = session.run("MATCH ()-[r:USES_COLUMN]->() RETURN count(r) as count")
        assert result.single()["count"] == 2

        # Should have table and column nodes (required for lineage)
        result = session.run("MATCH (t:Table) RETURN count(t) as count")
        assert result.single()["count"] == 3

        result = session.run("MATCH (c:Column) RETURN count(c) as count")
        assert result.single()["count"] == 5

        # Should NOT have database or schema nodes
        result = session.run("MATCH (d:Database) RETURN count(d) as count")
        assert result.single()["count"] == 0

        result = session.run("MATCH (s:Schema) RETURN count(s) as count")
        assert result.single()["count"] == 0


def test_verify_query_lineage(neo4j_driver, temp_csv_dir, all_sample_csvs):
    """Test that query lineage is correctly established."""
    workflow = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    workflow.ingest()

    with neo4j_driver.session(database="neo4j") as session:
        # Verify query q001 uses orders table
        result = session.run("""
            MATCH (q:Query {id: 'q001'})-[:USES_TABLE]->(t:Table)
            RETURN t.name as table_name
        """)
        record = result.single()
        assert record is not None
        assert record["table_name"] == "orders"

        # Verify query q002 uses customer_id column
        result = session.run("""
            MATCH (q:Query {id: 'q002'})-[:USES_COLUMN]->(c:Column)
            RETURN c.name as column_name
        """)
        record = result.single()
        assert record is not None
        assert record["column_name"] == "customer_id"
