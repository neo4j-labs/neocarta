"""Example: load JDBC schema metadata into the semantic graph via SchemaCrawler.

Requires Java 11+, a SchemaCrawler distribution JAR, and a JDBC driver JAR on
the host (see neocarta/connectors/jdbc/README.md). Configure the connection via
the JDBC_* environment variables (see .env.example).
"""

import argparse
import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

from neocarta import NodeLabel
from neocarta.connectors.jdbc import JdbcSchemaConnector
from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector


def main(schemas: list[str] | None = None, with_embeddings: bool = True) -> None:
    """Run the JDBC schema connector and optionally compute embeddings."""
    load_dotenv()
    print("Starting connector...")
    print("Creating drivers and clients...")
    neo4j_driver = GraphDatabase.driver(
        uri=os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
    )
    neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")

    node_labels = [NodeLabel.DATABASE, NodeLabel.SCHEMA, NodeLabel.TABLE, NodeLabel.COLUMN]

    print("Extracting, transforming, and loading JDBC schema metadata into Neo4j...")
    connector = JdbcSchemaConnector(
        jdbc_url=os.getenv("JDBC_URL"),
        jdbc_driver=os.getenv("JDBC_DRIVER"),
        jdbc_driver_jar=os.getenv("JDBC_DRIVER_JAR"),
        schemacrawler_jar=os.getenv("SCHEMACRAWLER_JAR"),
        neo4j_driver=neo4j_driver,
        database_name=neo4j_database,
        db_user=os.getenv("JDBC_USER"),
        db_password=os.getenv("JDBC_PASSWORD"),
    )
    connector.ingest(schemas=schemas)

    if with_embeddings:
        print("Generating embeddings for nodes...")
        embeddings_connector = LiteLLMEmbeddingsConnector(
            neo4j_driver=neo4j_driver,
            embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            database_name=neo4j_database,
        )
        embeddings_connector.run(node_labels=node_labels)

    print("Connector completed successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract JDBC schema metadata via SchemaCrawler and load into Neo4j "
        "(embeddings enabled by default)"
    )
    parser.add_argument(
        "--schemas",
        nargs="*",
        default=None,
        help="Schema names to include (space-separated). Omit to extract all schemas.",
    )
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Skip embedding generation (only load metadata into Neo4j)",
    )
    args = parser.parse_args()

    main(schemas=args.schemas, with_embeddings=not args.skip_embeddings)
