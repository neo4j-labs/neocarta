"""Example: load a source Neo4j's schema into the neocarta graph.

Reads a source Neo4j instance's schema (labels, relationship types, properties)
via APOC (``apoc.meta.schema()``) and maps it onto the LPG data model
(``Node`` / ``Relationship`` / ``Property`` under ``Database`` / ``Schema``).

The **source** instance must have the APOC (Core) plugin installed. Source and
target may be the same instance. Set in ``.env``:

* ``SOURCE_NEO4J_URI`` / ``SOURCE_NEO4J_USERNAME`` / ``SOURCE_NEO4J_PASSWORD`` — the source
* ``SOURCE_NAME`` — a stable name for the source DBMS (the Database node id)
* ``SOURCE_NEO4J_DATABASE`` — the source database to introspect (default ``neo4j``)
* ``NEO4J_URI`` / ``NEO4J_USERNAME`` / ``NEO4J_PASSWORD`` / ``NEO4J_DATABASE`` — the target
"""

import argparse
import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

from neocarta import NodeLabel
from neocarta.connectors.neo4j import Neo4jSchemaConnector
from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector


def main(with_embeddings: bool = True) -> None:
    """Run the Neo4j schema connector and optionally compute embeddings."""
    load_dotenv()

    print("Creating source and target Neo4j drivers...")
    source_driver = GraphDatabase.driver(
        os.getenv("SOURCE_NEO4J_URI"),
        auth=(os.getenv("SOURCE_NEO4J_USERNAME"), os.getenv("SOURCE_NEO4J_PASSWORD")),
    )
    target_driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
    )
    neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")

    # Close both drivers unconditionally — the connector never closes them (the
    # caller owns both, and they may be the same instance).
    try:
        print("Ingesting Neo4j schema metadata into the neocarta graph...")
        Neo4jSchemaConnector(
            source_neo4j_driver=source_driver,
            neo4j_driver=target_driver,
            source_name=os.getenv("SOURCE_NAME", "neo4j-source"),
            database_name=neo4j_database,
        ).ingest(source_database=os.getenv("SOURCE_NEO4J_DATABASE", "neo4j"))

        if with_embeddings:
            print("Generating embeddings for Node/Relationship nodes...")
            # Configure provider via env vars (e.g. OPENAI_API_KEY, GEMINI_API_KEY).
            LiteLLMEmbeddingsConnector(
                neo4j_driver=target_driver,
                embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
                database_name=neo4j_database,
            ).run(node_labels=[NodeLabel.NODE, NodeLabel.RELATIONSHIP])
    finally:
        source_driver.close()
        target_driver.close()

    print("Connector completed successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Introspect a source Neo4j's schema (via APOC) into the neocarta LPG graph. "
            "Embeddings enabled by default."
        )
    )
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Skip embedding generation (only load the schema into Neo4j).",
    )
    args = parser.parse_args()

    main(with_embeddings=not args.skip_embeddings)
