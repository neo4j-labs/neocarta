"""Example: load the MusicBrainz schema into the semantic graph.

MusicBrainz exposes no ``INFORMATION_SCHEMA`` endpoint, so its core relational
schema (12 tables, 86 columns, 11 foreign keys) is described as CSV files under
``datasets/musicbrainz/`` and loaded with the generic :class:`CSVConnector`.

Embeddings are generated with :class:`LiteLLMEmbeddingsConnector` (the provider-
agnostic default used across the examples). For ``text-embedding-3-small`` the
vector dimension is auto-detected to 1536, matching the query embeddings the
Neocarta MCP server produces, so the semantic MCP retrieval tools work without
any server changes.
"""

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

from neocarta import NodeLabel, RelationshipType
from neocarta.connectors.csv import CSVConnector
from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector

# Resolved from this file's location so the script runs from any directory.
MUSICBRAINZ_CSV_DIRECTORY = Path(__file__).resolve().parent.parent / "datasets" / "musicbrainz"


def main(with_embeddings: bool = True) -> None:
    """Run the MusicBrainz CSV connector and optionally compute embeddings.

    Parameters
    ----------
    with_embeddings : bool
        When ``True`` (default) generate embeddings for the loaded Table and
        Column nodes (via LiteLLM) after the schema has been ingested.
    """
    load_dotenv()

    missing = [v for v in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD") if not os.getenv(v)]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    print("Starting MusicBrainz connector...")
    print("Creating Neo4j driver...")
    neo4j_driver = GraphDatabase.driver(
        uri=os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
    )
    neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")

    # The MusicBrainz schema only needs the core structural entities.
    node_labels = [NodeLabel.DATABASE, NodeLabel.SCHEMA, NodeLabel.TABLE, NodeLabel.COLUMN]
    rel_types = [
        RelationshipType.HAS_SCHEMA,
        RelationshipType.HAS_TABLE,
        RelationshipType.HAS_COLUMN,
        RelationshipType.REFERENCES,
    ]

    print("Extracting, transforming, and loading MusicBrainz schema into Neo4j...")
    connector = CSVConnector(
        csv_directory=str(MUSICBRAINZ_CSV_DIRECTORY),
        neo4j_driver=neo4j_driver,
        database_name=neo4j_database,
    )
    connector.ingest(
        include_nodes=node_labels,
        include_relationships=rel_types,
    )

    if with_embeddings:
        print("Generating embeddings for Table and Column nodes...")
        # Provider auth comes from the env vars LiteLLM expects for the chosen
        # model (e.g. OPENAI_API_KEY for text-embedding-3-small). The dimension
        # is auto-detected (1536 for text-embedding-3-small).
        embeddings_connector = LiteLLMEmbeddingsConnector(
            neo4j_driver=neo4j_driver,
            embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            database_name=neo4j_database,
        )
        embeddings_connector.run(node_labels=[NodeLabel.TABLE, NodeLabel.COLUMN])

    neo4j_driver.close()
    print("MusicBrainz connector completed successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Load the MusicBrainz schema into Neo4j (embeddings enabled by default)"
    )
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Skip embedding generation (only load schema metadata into Neo4j)",
    )
    args = parser.parse_args()

    main(with_embeddings=not args.skip_embeddings)
