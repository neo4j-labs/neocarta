"""Example: load BigQuery schema metadata into the semantic graph."""

import argparse
import os

from dotenv import load_dotenv
from google.cloud import bigquery
from neo4j import GraphDatabase

from neocarta import NodeLabel
from neocarta.connectors.bigquery import BigQuerySchemaConnector
from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector


def main(with_embeddings: bool = True) -> None:
    """Run the BigQuery schema connector and optionally compute embeddings."""
    load_dotenv()
    print("Starting connector...")
    print("Creating drivers and clients...")
    neo4j_driver = GraphDatabase.driver(
        uri=os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
    )
    neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")
    bigquery_client = bigquery.Client(project=os.getenv("GCP_PROJECT_ID"))

    # Enum members are recommended, but exact string values (e.g. "Table", "Column") also work.
    node_labels = [NodeLabel.DATABASE, NodeLabel.SCHEMA, NodeLabel.TABLE, NodeLabel.COLUMN]

    print("Extracting, transforming, and loading BigQuery data into Neo4j...")
    # extract, transform, and load BigQuery data into Neo4j
    bigquery_connector = BigQuerySchemaConnector(
        client=bigquery_client,
        project_id=os.getenv("GCP_PROJECT_ID"),
        dataset_id=os.getenv("BIGQUERY_DATASET_ID"),
        neo4j_driver=neo4j_driver,
        database_name=neo4j_database,
    )
    bigquery_connector.run()

    if with_embeddings:
        print("Generating embeddings for nodes...")
        # create embeddings for the nodes; configure via env vars for the chosen provider
        # (e.g. OPENAI_API_KEY, GEMINI_API_KEY).
        embeddings_connector = LiteLLMEmbeddingsConnector(
            neo4j_driver=neo4j_driver,
            embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            database_name=neo4j_database,
        )
        embeddings_connector.run(node_labels=node_labels)

    print("Connector completed successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract BigQuery metadata and load into Neo4j (embeddings enabled by default)"
    )
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Skip embedding generation (only load metadata into Neo4j)",
    )
    args = parser.parse_args()

    main(with_embeddings=not args.skip_embeddings)
