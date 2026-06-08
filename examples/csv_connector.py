"""
CSV Connector Example.

Load metadata from CSV files into Neo4j using the CSVConnector.

The example dataset is located in datasets/csv/ and contains a complete
e-commerce schema with tables, columns, foreign keys, queries, and business glossary.
"""

import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

from neocarta import NodeLabel, RelationshipType
from neocarta.connectors.csv import CSVConnector


def main() -> None:
    """Load metadata from CSV files into Neo4j."""
    # Load environment variables
    load_dotenv()

    # Setup Neo4j connection
    neo4j_driver = GraphDatabase.driver(
        uri=os.getenv("NEO4J_URI"), auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD"))
    )
    neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")

    # if using non-default CSV file map, pass it to the connector
    file_map = {
        NodeLabel.DATABASE: "database_info.csv",
        NodeLabel.SCHEMA: "schema_info.csv",
        NodeLabel.TABLE: "table_info.csv",
        NodeLabel.COLUMN: "column_info.csv",
        NodeLabel.VALUE: "value_info.csv",
        # ...
    }

    # Initialize CSV connector
    connector = CSVConnector(
        csv_directory="datasets/csv",
        neo4j_driver=neo4j_driver,
        database_name=neo4j_database,
        csv_file_map=file_map,
    )

    # by default, load all nodes and relationships
    # * structural nodes and relationships
    # * sql query nodes and relationships
    # * terminology nodes and relationships

    # Here we define which nodes and relationships to load.
    # Enum members are recommended, but exact string values (e.g. "Database", "HAS_SCHEMA") also work.
    include_nodes = [
        NodeLabel.DATABASE,
        NodeLabel.SCHEMA,
        NodeLabel.TABLE,
        NodeLabel.COLUMN,
        NodeLabel.VALUE,
        NodeLabel.QUERY,
        # NodeLabel.GLOSSARY,
        # NodeLabel.CATEGORY,
        # NodeLabel.BUSINESS_TERM,
    ]
    include_relationships = [
        RelationshipType.HAS_SCHEMA,
        RelationshipType.HAS_TABLE,
        RelationshipType.HAS_COLUMN,
        RelationshipType.HAS_VALUE,
        RelationshipType.REFERENCES,
        RelationshipType.USES_TABLE,
        RelationshipType.USES_COLUMN,
        # RelationshipType.HAS_CATEGORY,
        # RelationshipType.HAS_BUSINESS_TERM,
        # RelationshipType.TAGGED_WITH,
    ]
    # Run the connector to load all CSV files
    connector.ingest(include_nodes=include_nodes, include_relationships=include_relationships)

    # Cleanup
    neo4j_driver.close()
    print("\nConnector completed successfully!")


if __name__ == "__main__":
    main()
