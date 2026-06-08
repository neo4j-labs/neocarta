"""Example: load only Dataplex business glossary metadata into the semantic graph.

Use this when you want glossary content (Glossary / Category / BusinessTerm nodes)
without the BigQuery catalog schema. The catalog↔glossary TAGGED_WITH edges are
enabled by default; pass ``--skip-entry-links`` if the BigQuery catalog isn't in
this Neo4j instance and the TAGGED_WITH edges would dangle.

To also load the catalog schema, use ``examples/dataplex.py``.
"""

import argparse
import os

from dotenv import load_dotenv
from google.cloud import dataplex_v1
from neo4j import GraphDatabase

from neocarta import NodeLabel
from neocarta.connectors.dataplex import DataplexGlossaryConnector
from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector


def main(with_embeddings: bool = True, include_entry_links: bool = True) -> None:
    """Run the Dataplex glossary connector and optionally compute embeddings."""
    load_dotenv()
    print("Starting Dataplex glossary connector...")
    print("Creating drivers and clients...")

    neo4j_driver = GraphDatabase.driver(
        uri=os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
    )
    neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")

    glossary_client = dataplex_v1.BusinessGlossaryServiceClient()

    print("Ingesting Dataplex glossary metadata into Neo4j...")
    DataplexGlossaryConnector(
        glossary_client=glossary_client,
        project_id=os.getenv("GCP_PROJECT_ID"),
        project_number=os.getenv("GCP_PROJECT_NUMBER"),
        dataplex_location=os.getenv("DATAPLEX_LOCATION"),
        neo4j_driver=neo4j_driver,
        database_name=neo4j_database,
    ).ingest(include_entry_links=include_entry_links)

    if with_embeddings:
        print("Generating embeddings for BusinessTerm nodes...")
        # Configure provider via env vars (e.g. OPENAI_API_KEY, GEMINI_API_KEY).
        embeddings = LiteLLMEmbeddingsConnector(
            neo4j_driver=neo4j_driver,
            embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            database_name=neo4j_database,
        )
        embeddings.run(node_labels=[NodeLabel.BUSINESS_TERM])

    print("Connector completed successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Extract Dataplex glossary metadata (Glossary, Category, BusinessTerm) "
            "and load into Neo4j. Embeddings enabled by default."
        )
    )
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Skip embedding generation (only load metadata into Neo4j)",
    )
    parser.add_argument(
        "--skip-entry-links",
        action="store_true",
        help=(
            "Skip catalog↔glossary entry links (TAGGED_WITH edges). "
            "Use when the BigQuery catalog is not present in this Neo4j instance."
        ),
    )
    args = parser.parse_args()

    main(
        with_embeddings=not args.skip_embeddings,
        include_entry_links=not args.skip_entry_links,
    )
