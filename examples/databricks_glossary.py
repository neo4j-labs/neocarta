"""Example: load Databricks Unity Catalog governed-tag definitions as a glossary.

Reads governed-tag *definitions* (tag policies) from a managed Databricks
workspace via the Databricks SDK — no SQL warehouse required — and maps them into
the business-glossary layer: one account-level Glossary, a Category per tag key,
and a BusinessTerm per allowed value.

Requires the ``databricks`` extra: ``pip install neocarta[databricks]`` (or
``uv sync --all-extras``). Tag *assignments* (TAGGED_WITH edges to columns/tables)
are not read in v1.
"""

import argparse
import os

from databricks.sdk import WorkspaceClient
from dotenv import load_dotenv
from neo4j import GraphDatabase

from neocarta import NodeLabel
from neocarta.connectors.databricks import DatabricksGlossaryConnector
from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector


def main(with_embeddings: bool = True, include_system_tags: bool = False) -> None:
    """Run the Databricks glossary connector and optionally compute embeddings."""
    load_dotenv()
    print("Starting Databricks governed-tags glossary connector...")
    print("Creating drivers and clients...")

    neo4j_driver = GraphDatabase.driver(
        uri=os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
    )
    neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")

    # The SDK natively honors DATABRICKS_HOST / DATABRICKS_TOKEN (and other
    # unified-auth env vars) when built without arguments.
    workspace_client = WorkspaceClient(
        host=os.getenv("DATABRICKS_HOST"),
        token=os.getenv("DATABRICKS_TOKEN"),
    )

    print("Ingesting Databricks governed-tag metadata into Neo4j...")
    DatabricksGlossaryConnector(
        workspace_client=workspace_client,
        neo4j_driver=neo4j_driver,
        database_name=neo4j_database,
    ).ingest(include_system_tags=include_system_tags)

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
            "Extract Databricks governed-tag definitions (Glossary, Category, BusinessTerm) "
            "and load into Neo4j. Embeddings enabled by default."
        )
    )
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Skip embedding generation (only load metadata into Neo4j)",
    )
    parser.add_argument(
        "--include-system-tags",
        action="store_true",
        help="Also ingest platform-managed system.* governed tags (excluded by default).",
    )
    args = parser.parse_args()

    main(
        with_embeddings=not args.skip_embeddings,
        include_system_tags=args.include_system_tags,
    )
