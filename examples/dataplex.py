"""Example: load Dataplex metadata into the semantic graph."""

import argparse
import os

from dotenv import load_dotenv
from google.cloud import dataplex_v1
from neo4j import GraphDatabase

from neocarta import NodeLabel
from neocarta.connectors.dataplex import DataplexConnector
from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector


def main(
    with_embeddings: bool = True,
    include_schema: bool = True,
    include_glossary: bool = True,
) -> None:
    """Run the Dataplex connector and optionally compute embeddings."""
    load_dotenv()
    print("Starting Dataplex connector...")
    print("Creating drivers and clients...")

    neo4j_driver = GraphDatabase.driver(
        uri=os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
    )
    neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")

    catalog_client = dataplex_v1.CatalogServiceClient()
    glossary_client = dataplex_v1.BusinessGlossaryServiceClient()

    # Node labels to embed — filtered to what was actually ingested.
    # Enum members are recommended, but exact string values (e.g. "Table", "BusinessTerm") also work.
    node_labels: list[NodeLabel] = []
    if include_schema:
        node_labels += [NodeLabel.TABLE, NodeLabel.COLUMN]
    if include_glossary:
        node_labels += [NodeLabel.BUSINESS_TERM]

    print("Extracting, transforming, and loading Dataplex metadata into Neo4j...")
    connector = DataplexConnector(
        catalog_client=catalog_client,
        glossary_client=glossary_client,
        project_id=os.getenv("GCP_PROJECT_ID"),
        project_number=os.getenv("GCP_PROJECT_NUMBER"),
        dataplex_location=os.getenv("DATAPLEX_LOCATION"),
        dataset_id=os.getenv("BIGQUERY_DATASET_ID"),
        neo4j_driver=neo4j_driver,
        database_name=neo4j_database,
        include_schema=include_schema,
        include_glossary=include_glossary,
    )
    connector.run()

    if with_embeddings and node_labels:
        print("Generating embeddings for nodes...")
        # Configure provider via env vars (e.g. OPENAI_API_KEY, GEMINI_API_KEY).
        embeddings = LiteLLMEmbeddingsConnector(
            neo4j_driver=neo4j_driver,
            embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            database_name=neo4j_database,
        )
        embeddings.run(node_labels=node_labels)

    print("Connector completed successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract Dataplex metadata and load into Neo4j (embeddings enabled by default)"
    )
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Skip embedding generation (only load metadata into Neo4j)",
    )
    parser.add_argument(
        "--skip-schema",
        action="store_true",
        help="Skip BigQuery schema ingestion (Database, Schema, Table, Column)",
    )
    parser.add_argument(
        "--skip-glossary",
        action="store_true",
        help="Skip business glossary ingestion (Glossary, Category, BusinessTerm)",
    )
    args = parser.parse_args()

    main(
        with_embeddings=not args.skip_embeddings,
        include_schema=not args.skip_schema,
        include_glossary=not args.skip_glossary,
    )
