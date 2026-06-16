"""Example: load open Unity Catalog REST API schema metadata into the semantic graph.

Talks to any conformant open Unity Catalog server (a local OSS server, a
self-hosted deployment, or a managed one) over the `/api/2.1/unity-catalog`
REST API. Configure the connection via the `UC_*` environment variables (see
.env.example). A local OSS server needs no token.
"""

import argparse
import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

from neocarta import NodeLabel
from neocarta.connectors.unity_catalog import UnityCatalogSchemaConnector
from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector


def main(
    catalog: str,
    schemas: list[str] | None = None,
    with_embeddings: bool = True,
) -> None:
    """Run the Unity Catalog schema connector and optionally compute embeddings."""
    load_dotenv()
    print("Starting Unity Catalog connector...")
    print("Creating drivers and clients...")
    neo4j_driver = GraphDatabase.driver(
        uri=os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
    )
    neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")

    node_labels = [NodeLabel.DATABASE, NodeLabel.SCHEMA, NodeLabel.TABLE, NodeLabel.COLUMN]

    print("Extracting, transforming, and loading Unity Catalog schema metadata into Neo4j...")
    connector = UnityCatalogSchemaConnector(
        base_url=os.getenv("UC_SERVER_URL", "http://localhost:8080/api/2.1/unity-catalog"),
        token=os.getenv("UC_TOKEN"),  # optional; None for a local OSS server
        neo4j_driver=neo4j_driver,
        database_name=neo4j_database,
    )
    connector.ingest(catalog=catalog, schemas=schemas)

    if with_embeddings:
        print("Generating embeddings for nodes...")
        # Configure provider via env vars (e.g. OPENAI_API_KEY, GEMINI_API_KEY).
        embeddings_connector = LiteLLMEmbeddingsConnector(
            neo4j_driver=neo4j_driver,
            embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            database_name=neo4j_database,
        )
        embeddings_connector.run(node_labels=node_labels)

    print("Connector completed successfully!")
    neo4j_driver.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract open Unity Catalog REST API schema metadata and load into Neo4j "
        "(embeddings enabled by default)"
    )
    parser.add_argument(
        "--catalog",
        default=os.getenv("UC_CATALOG", "unity"),
        help="Unity Catalog catalog name to ingest (default: UC_CATALOG env or 'unity').",
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

    main(
        catalog=args.catalog,
        schemas=args.schemas,
        with_embeddings=not args.skip_embeddings,
    )
