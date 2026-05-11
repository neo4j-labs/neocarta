"""Integration tests for CSV connector workflow."""

from neocarta.connectors.csv import CSVConnector
from neocarta.enums import NodeLabel, RelationshipType


def test_load_database_nodes(neo4j_driver, temp_csv_dir, sample_database_csv):
    """Test that database nodes are loaded correctly."""
    connector = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    connector.run(include_nodes=[NodeLabel.DATABASE])

    with neo4j_driver.session(database="neo4j") as session:
        result = session.run(
            "MATCH (d:Database) RETURN d.id as id, d.name as name, d.platform as platform"
        )
        records = list(result)

        assert len(records) == 1
        assert records[0]["id"] == "my_project"
        assert records[0]["name"] == "my-project"
        assert records[0]["platform"] == "GCP"


def test_database_only_loads_provided_columns(neo4j_driver, temp_csv_dir):
    """Test that only CSV columns are loaded as properties, not all possible fields."""
    (temp_csv_dir / "database_info.csv").write_text("database_name,platform\ntest-db,AWS\n")

    connector = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    connector.run(include_nodes=[NodeLabel.DATABASE])

    with neo4j_driver.session(database="neo4j") as session:
        result = session.run("MATCH (d:Database) RETURN properties(d) as props")
        props = result.single()["props"]

        assert "id" in props
        assert "name" in props
        assert "platform" in props
        # Not in CSV — should not be written
        assert "description" not in props
        assert "service" not in props


def test_load_schema_nodes(neo4j_driver, temp_csv_dir, sample_database_csv, sample_schema_csv):
    """Test that schema nodes are loaded correctly."""
    connector = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    connector.run(include_nodes=[NodeLabel.DATABASE, NodeLabel.SCHEMA])

    with neo4j_driver.session(database="neo4j") as session:
        result = session.run("MATCH (s:Schema) RETURN s.name as name ORDER BY s.name")
        records = list(result)

        assert len(records) == 2
        assert records[0]["name"] == "analytics"
        assert records[1]["name"] == "sales"


def test_schema_only_loads_provided_columns(neo4j_driver, temp_csv_dir):
    """Test that only CSV columns are loaded for schemas."""
    (temp_csv_dir / "database_info.csv").write_text("database_name\nmy-project\n")
    (temp_csv_dir / "schema_info.csv").write_text("database_name,schema_name\nmy-project,sales\n")

    connector = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    connector.run(include_nodes=[NodeLabel.DATABASE, NodeLabel.SCHEMA])

    with neo4j_driver.session(database="neo4j") as session:
        result = session.run("MATCH (s:Schema) RETURN properties(s) as props")
        props = result.single()["props"]

        assert "id" in props
        assert "name" in props
        assert "description" not in props


def test_load_has_schema_relationships(
    neo4j_driver, temp_csv_dir, sample_database_csv, sample_schema_csv
):
    """Test that HAS_SCHEMA relationships are created."""
    connector = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    connector.run(
        include_nodes=[NodeLabel.DATABASE, NodeLabel.SCHEMA],
        include_relationships=[RelationshipType.HAS_SCHEMA],
    )

    with neo4j_driver.session(database="neo4j") as session:
        result = session.run(
            "MATCH (d:Database)-[:HAS_SCHEMA]->(s:Schema) "
            "RETURN d.id as db_id, s.name as schema_name ORDER BY s.name"
        )
        records = list(result)

        assert len(records) == 2
        assert records[0]["db_id"] == "my_project"
        assert records[0]["schema_name"] == "analytics"


def test_load_table_nodes(
    neo4j_driver, temp_csv_dir, sample_database_csv, sample_schema_csv, sample_table_csv
):
    """Test that table nodes are loaded correctly."""
    connector = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    connector.run(include_nodes=[NodeLabel.DATABASE, NodeLabel.SCHEMA, NodeLabel.TABLE])

    with neo4j_driver.session(database="neo4j") as session:
        result = session.run("MATCH (t:Table) RETURN t.name as name ORDER BY t.name")
        records = list(result)

        assert len(records) == 3
        assert records[0]["name"] == "customers"
        assert records[1]["name"] == "orders"
        assert records[2]["name"] == "summary"


def test_load_column_nodes(
    neo4j_driver,
    temp_csv_dir,
    sample_database_csv,
    sample_schema_csv,
    sample_table_csv,
    sample_column_csv,
):
    """Test that column nodes are loaded correctly."""
    connector = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    connector.run(
        include_nodes=[NodeLabel.DATABASE, NodeLabel.SCHEMA, NodeLabel.TABLE, NodeLabel.COLUMN]
    )

    with neo4j_driver.session(database="neo4j") as session:
        result = session.run(
            "MATCH (c:Column) "
            "RETURN c.name as name, c.type as type, c.is_primary_key as is_pk "
            "ORDER BY c.name"
        )
        records = list(result)

        assert len(records) == 5
        customer_id_cols = [r for r in records if r["name"] == "customer_id"]
        assert len(customer_id_cols) == 2


def test_column_only_loads_provided_columns(neo4j_driver, temp_csv_dir):
    """Test that only CSV columns are loaded for columns."""
    (temp_csv_dir / "database_info.csv").write_text("database_name\nmy-project\n")
    (temp_csv_dir / "schema_info.csv").write_text("database_name,schema_name\nmy-project,sales\n")
    (temp_csv_dir / "table_info.csv").write_text(
        "database_name,schema_name,table_name\nmy-project,sales,orders\n"
    )
    (temp_csv_dir / "column_info.csv").write_text(
        "database_name,schema_name,table_name,column_name,is_nullable,is_primary_key\n"
        "my-project,sales,orders,order_id,false,true\n"
    )

    connector = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    connector.run(
        include_nodes=[NodeLabel.DATABASE, NodeLabel.SCHEMA, NodeLabel.TABLE, NodeLabel.COLUMN]
    )

    with neo4j_driver.session(database="neo4j") as session:
        result = session.run("MATCH (c:Column) RETURN properties(c) as props")
        props = result.single()["props"]

        assert "id" in props
        assert "name" in props
        assert "nullable" in props
        assert "is_primary_key" in props
        # Not in CSV — should not be written
        assert "type" not in props
        assert "description" not in props
        assert "is_foreign_key" not in props


def test_column_properties_correct_values(neo4j_driver, temp_csv_dir):
    """Test that column properties are set with correct values."""
    (temp_csv_dir / "database_info.csv").write_text("database_name\nmy-project\n")
    (temp_csv_dir / "schema_info.csv").write_text("database_name,schema_name\nmy-project,sales\n")
    (temp_csv_dir / "table_info.csv").write_text(
        "database_name,schema_name,table_name\nmy-project,sales,orders\n"
    )
    (temp_csv_dir / "column_info.csv").write_text(
        "database_name,schema_name,table_name,column_name,data_type,is_nullable,is_primary_key,is_foreign_key\n"
        "my-project,sales,orders,order_id,STRING,false,true,false\n"
    )

    connector = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    connector.run(
        include_nodes=[NodeLabel.DATABASE, NodeLabel.SCHEMA, NodeLabel.TABLE, NodeLabel.COLUMN]
    )

    with neo4j_driver.session(database="neo4j") as session:
        result = session.run(
            "MATCH (c:Column {name: 'order_id'}) "
            "RETURN c.is_primary_key as is_pk, c.is_foreign_key as is_fk, c.nullable as nullable"
        )
        record = result.single()

        assert record["is_pk"]
        assert not record["is_fk"]
        assert not record["nullable"]


def test_load_references_relationships(neo4j_driver, temp_csv_dir):
    """Test that REFERENCES relationships are created."""
    (temp_csv_dir / "database_info.csv").write_text("database_name\nmy-project\n")
    (temp_csv_dir / "schema_info.csv").write_text("database_name,schema_name\nmy-project,sales\n")
    (temp_csv_dir / "table_info.csv").write_text(
        "database_name,schema_name,table_name\nmy-project,sales,orders\nmy-project,sales,customers\n"
    )
    (temp_csv_dir / "column_info.csv").write_text(
        "database_name,schema_name,table_name,column_name\n"
        "my-project,sales,orders,customer_id\n"
        "my-project,sales,customers,customer_id\n"
    )
    (temp_csv_dir / "column_references_info.csv").write_text(
        "source_database_name,source_schema_name,source_table_name,source_column_name,"
        "target_database_name,target_schema_name,target_table_name,target_column_name,criteria\n"
        "my-project,sales,orders,customer_id,my-project,sales,customers,customer_id,"
        "orders.customer_id = customers.customer_id\n"
    )

    connector = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    connector.run(
        include_nodes=[NodeLabel.DATABASE, NodeLabel.SCHEMA, NodeLabel.TABLE, NodeLabel.COLUMN],
        include_relationships=[
            RelationshipType.HAS_SCHEMA,
            RelationshipType.HAS_TABLE,
            RelationshipType.HAS_COLUMN,
            RelationshipType.REFERENCES,
        ],
    )

    with neo4j_driver.session(database="neo4j") as session:
        result = session.run(
            "MATCH (c1:Column)-[r:REFERENCES]->(c2:Column) "
            "RETURN c1.name as source, c2.name as target, r.criteria as criteria"
        )
        records = list(result)

        assert len(records) == 1
        assert records[0]["source"] == "customer_id"
        assert records[0]["target"] == "customer_id"
        assert "customers" in records[0]["criteria"]


def test_load_value_nodes(neo4j_driver, temp_csv_dir):
    """Test that value nodes are loaded correctly."""
    (temp_csv_dir / "database_info.csv").write_text("database_name\nmy-project\n")
    (temp_csv_dir / "schema_info.csv").write_text("database_name,schema_name\nmy-project,sales\n")
    (temp_csv_dir / "table_info.csv").write_text(
        "database_name,schema_name,table_name\nmy-project,sales,orders\n"
    )
    (temp_csv_dir / "column_info.csv").write_text(
        "database_name,schema_name,table_name,column_name\nmy-project,sales,orders,status\n"
    )
    (temp_csv_dir / "value_info.csv").write_text(
        "database_name,schema_name,table_name,column_name,value\n"
        "my-project,sales,orders,status,pending\n"
        "my-project,sales,orders,status,completed\n"
        "my-project,sales,orders,status,cancelled\n"
    )

    connector = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    connector.run(
        include_nodes=[
            NodeLabel.DATABASE,
            NodeLabel.SCHEMA,
            NodeLabel.TABLE,
            NodeLabel.COLUMN,
            NodeLabel.VALUE,
        ]
    )

    with neo4j_driver.session(database="neo4j") as session:
        result = session.run("MATCH (v:Value) RETURN v.value as value ORDER BY v.value")
        records = list(result)

        assert len(records) == 3
        values = [r["value"] for r in records]
        assert "pending" in values
        assert "completed" in values
        assert "cancelled" in values


def test_load_query_nodes(neo4j_driver, temp_csv_dir, sample_query_csv):
    """Test that query nodes are loaded correctly."""
    connector = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    connector.run(include_nodes=[NodeLabel.QUERY])

    with neo4j_driver.session(database="neo4j") as session:
        result = session.run(
            "MATCH (q:Query) RETURN q.id as id, q.content as content ORDER BY q.id"
        )
        records = list(result)

        assert len(records) == 2
        assert records[0]["id"] == "q001"
        assert "order_id" in records[0]["content"]


def test_query_only_loads_provided_columns(neo4j_driver, temp_csv_dir):
    """Test that only CSV columns are loaded for queries."""
    (temp_csv_dir / "query_info.csv").write_text("query_id,content\nq001,SELECT * FROM table\n")

    connector = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    connector.run(include_nodes=[NodeLabel.QUERY])

    with neo4j_driver.session(database="neo4j") as session:
        result = session.run("MATCH (q:Query) RETURN properties(q) as props")
        props = result.single()["props"]

        assert "id" in props
        assert "content" in props
        assert "description" not in props


def test_load_glossary_entities(neo4j_driver, temp_csv_dir):
    """Test that glossary entities are loaded correctly."""
    (temp_csv_dir / "glossary_info.csv").write_text(
        "glossary_name,name,description\nsales_glossary,Sales Glossary,Sales business terms\n"
    )
    (temp_csv_dir / "category_info.csv").write_text(
        "glossary_name,category_name,name,description\nsales_glossary,metrics,Metrics,Sales metrics\n"
    )
    (temp_csv_dir / "business_term_info.csv").write_text(
        "glossary_name,category_name,term_name,name,description\nsales_glossary,metrics,arr,Annual Recurring Revenue,Yearly revenue\n"
    )

    connector = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    connector.run(
        include_nodes=[NodeLabel.GLOSSARY, NodeLabel.CATEGORY, NodeLabel.BUSINESS_TERM],
        include_relationships=[RelationshipType.HAS_CATEGORY, RelationshipType.HAS_BUSINESS_TERM],
    )

    with neo4j_driver.session(database="neo4j") as session:
        result = session.run(
            "MATCH (g:Glossary)-[:HAS_CATEGORY]->(c:Category)-[:HAS_BUSINESS_TERM]->(t:BusinessTerm) "
            "RETURN g.name as glossary, c.name as category, t.name as term"
        )
        record = result.single()

        assert record["glossary"] == "Sales Glossary"
        assert record["category"] == "Metrics"
        assert record["term"] == "Annual Recurring Revenue"


def test_run_complete_workflow(neo4j_driver, temp_csv_dir, all_sample_csvs):
    """Test that the complete workflow runs successfully."""
    connector = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    connector.run()

    with neo4j_driver.session(database="neo4j") as session:
        node_counts = {}
        for label in [
            "Database",
            "Schema",
            "Table",
            "Column",
            "Value",
            "Query",
            "Glossary",
            "Category",
            "BusinessTerm",
        ]:
            result = session.run(f"MATCH (n:{label}) RETURN count(n) as count")
            node_counts[label] = result.single()["count"]

        assert node_counts["Database"] == 1
        assert node_counts["Schema"] == 2
        assert node_counts["Table"] == 3
        assert node_counts["Column"] == 5
        assert node_counts["Value"] == 3
        assert node_counts["Query"] == 2
        assert node_counts["Glossary"] == 1
        assert node_counts["Category"] == 1
        assert node_counts["BusinessTerm"] == 1

        rel_counts = {}
        for rel_type in [
            "HAS_SCHEMA",
            "HAS_TABLE",
            "HAS_COLUMN",
            "REFERENCES",
            "HAS_VALUE",
            "USES_TABLE",
        ]:
            result = session.run(f"MATCH ()-[r:{rel_type}]->() RETURN count(r) as count")
            rel_counts[rel_type] = result.single()["count"]

        assert rel_counts["HAS_SCHEMA"] == 2
        assert rel_counts["HAS_TABLE"] == 3
        assert rel_counts["HAS_COLUMN"] == 5
        assert rel_counts["REFERENCES"] == 1
        assert rel_counts["HAS_VALUE"] == 3
        assert rel_counts["USES_TABLE"] == 2


def test_minimal_csv_with_only_required_fields(neo4j_driver, temp_csv_dir):
    """Test that CSV with only required fields works correctly."""
    (temp_csv_dir / "database_info.csv").write_text("database_name\nminimal-db\n")
    (temp_csv_dir / "schema_info.csv").write_text("database_name,schema_name\nminimal-db,schema1\n")
    (temp_csv_dir / "table_info.csv").write_text(
        "database_name,schema_name,table_name\nminimal-db,schema1,table1\n"
    )
    (temp_csv_dir / "column_info.csv").write_text(
        "database_name,schema_name,table_name,column_name\nminimal-db,schema1,table1,col1\n"
    )

    connector = CSVConnector(
        csv_directory=str(temp_csv_dir), neo4j_driver=neo4j_driver, database_name="neo4j"
    )

    connector.run()

    with neo4j_driver.session(database="neo4j") as session:
        db_props = session.run("MATCH (d:Database) RETURN properties(d) as props").single()["props"]
        assert "id" in db_props
        assert "name" in db_props
        assert len([k for k in db_props if not k.startswith("_")]) == 2

        rel_count = session.run("MATCH ()-[r:HAS_SCHEMA]->() RETURN count(r) as count").single()[
            "count"
        ]
        assert rel_count == 1
