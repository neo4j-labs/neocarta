"""Example: load Databricks Unity Catalog governed-tag definitions as governance tags.

Reads governed-tag *definitions* (tag policies) from a managed Databricks
workspace via the Databricks SDK — no SQL warehouse required — and maps them into
the vendor-neutral governance-tag layer: a GovernanceTagKey per tag key, a
GovernanceTagValue per allowed value, and a HAS_VALUE_OPTION edge between them.

Requires the ``databricks`` extra: ``pip install neocarta[databricks]`` (or
``uv sync --all-extras``). Tag *assignments* (TAGGED_WITH edges to columns/tables)
live in information_schema and are a planned follow-up.
"""

import argparse
import os

from databricks.sdk import WorkspaceClient
from dotenv import load_dotenv
from neo4j import GraphDatabase

from neocarta import NodeLabel
from neocarta.connectors.databricks import DatabricksTagsConnector
from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector


def main(with_embeddings: bool = True, include_system_tags: bool = False) -> None:
    """Run the Databricks governance-tags connector and optionally compute embeddings."""
    load_dotenv()
    print("Starting Databricks governance-tags connector...")
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
    DatabricksTagsConnector(
        workspace_client=workspace_client,
        neo4j_driver=neo4j_driver,
        database_name=neo4j_database,
    ).ingest(include_system_tags=include_system_tags)

    if with_embeddings:
        print("Generating embeddings for GovernanceTagKey nodes...")
        # Configure provider via env vars (e.g. OPENAI_API_KEY, GEMINI_API_KEY).
        embeddings = LiteLLMEmbeddingsConnector(
            neo4j_driver=neo4j_driver,
            embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            database_name=neo4j_database,
        )
        embeddings.run(node_labels=[NodeLabel.GOVERNANCE_TAG_KEY])

    print("Connector completed successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Extract Databricks governed-tag definitions (GovernanceTagKey, GovernanceTagValue) "
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
