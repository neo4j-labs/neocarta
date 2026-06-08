"""
Async Embeddings Example.

This example demonstrates how to generate embeddings asynchronously
on an existing Neo4j graph using LiteLLM (multi-provider).

This is useful when you want to parallelize embedding generation for
better performance on large datasets.

Usage:
    # Generate embeddings asynchronously for all node types
    python examples/async_embeddings.py

    # Generate embeddings for specific node types
    python examples/async_embeddings.py --node-labels Table Column

    # Use custom batch size
    python examples/async_embeddings.py --batch-size 200

Environment Variables Required:
    - NEO4J_URI: Neo4j connection URI
    - NEO4J_USERNAME: Neo4j username
    - NEO4J_PASSWORD: Neo4j password
    - NEO4J_DATABASE: Neo4j database name (optional, defaults to 'neo4j')
    - EMBEDDING_MODEL: LiteLLM model id (optional, defaults to 'text-embedding-3-small').
      The vector dimension is auto-detected from the model on first use.
    - Provider credentials, e.g. OPENAI_API_KEY, GEMINI_API_KEY, COHERE_API_KEY,
      AZURE_API_KEY/AZURE_API_BASE, AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY/AWS_REGION_NAME
"""

import argparse
import asyncio
import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

from neocarta import NodeLabel
from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector


async def main(
    node_labels: list[NodeLabel] = [NodeLabel.TABLE, NodeLabel.COLUMN],
    batch_size: int = 100,
) -> None:
    """Compute and store embeddings for specified node labels asynchronously."""
    load_dotenv()
    print("Starting async embeddings process...")
    print("Creating drivers and clients...")

    neo4j_driver = GraphDatabase.driver(
        uri=os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
    )
    neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")

    print(f"Generating embeddings asynchronously for: {', '.join(node_labels)}")
    print(f"Batch size: {batch_size}")

    embeddings_connector = LiteLLMEmbeddingsConnector(
        neo4j_driver=neo4j_driver,
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        database_name=neo4j_database,
    )
    await embeddings_connector.arun(
        node_labels=node_labels,
        batch_size=batch_size,
    )

    print("Async embeddings process completed successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate embeddings asynchronously for existing Neo4j graph nodes"
    )
    parser.add_argument(
        "--node-labels",
        nargs="+",
        default=[NodeLabel.TABLE, NodeLabel.COLUMN],
        # Enum members are recommended, but exact string values (e.g. "Table", "Column") also work.
        help="Node labels to generate embeddings for (default: Table Column)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of nodes to process in each batch (default: 100)",
    )
    args = parser.parse_args()

    asyncio.run(
        main(
            node_labels=args.node_labels,
            batch_size=args.batch_size,
        )
    )
