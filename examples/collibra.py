"""
Collibra Data Catalog → Neo4j connector example.

Set the following environment variables before running:

    Required:
        COLLIBRA_URL         Root URL, e.g. https://myorg.collibra.com
        NEO4J_URI            Neo4j bolt URI, e.g. neo4j+s://xxx.databases.neo4j.io
        NEO4J_USERNAME       Neo4j username (default: neo4j)
        NEO4J_PASSWORD       Neo4j password

    Authentication (one of):
        COLLIBRA_TOKEN       JWT Bearer token  (preferred for production)
        COLLIBRA_USERNAME    Collibra username  (basic auth)
        COLLIBRA_PASSWORD    Collibra password  (basic auth)

    Optional scope filters:
        COLLIBRA_COMMUNITY_IDS   Comma-separated community UUIDs to restrict extraction
        COLLIBRA_DOMAIN_IDS      Comma-separated domain UUIDs to restrict extraction

Run with:
    uv run examples/collibra.py
"""

import os

from neo4j import GraphDatabase

from neocarta.connectors.collibra import CollibraConnector


def main() -> None:
    """Run the Collibra → Neo4j ETL pipeline."""
    collibra_url = os.environ["COLLIBRA_URL"]
    neo4j_uri = os.environ["NEO4J_URI"]
    neo4j_user = os.environ.get("NEO4J_USERNAME", "neo4j")
    neo4j_password = os.environ["NEO4J_PASSWORD"]

    token = os.environ.get("COLLIBRA_TOKEN")
    username = os.environ.get("COLLIBRA_USERNAME")
    password = os.environ.get("COLLIBRA_PASSWORD")

    community_ids_raw = os.environ.get("COLLIBRA_COMMUNITY_IDS")
    community_ids = community_ids_raw.split(",") if community_ids_raw else None

    domain_ids_raw = os.environ.get("COLLIBRA_DOMAIN_IDS")
    domain_ids = domain_ids_raw.split(",") if domain_ids_raw else None

    with GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password)) as driver:
        connector = CollibraConnector(
            collibra_url=collibra_url,
            neo4j_driver=driver,
            token=token,
            username=username,
            password=password,
            community_ids=community_ids,
            domain_ids=domain_ids,
            include_lineage=True,
        )
        connector.run(overwrite_existing=False)

    print("Collibra ingestion complete.")


if __name__ == "__main__":
    main()
