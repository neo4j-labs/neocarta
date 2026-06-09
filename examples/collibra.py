"""
Collibra Data Catalog → Neo4j connector example.

Runs both Collibra source sub-connectors:

* ``CollibraSchemaConnector``   — physical layer (Database/Schema/Table/Column)
* ``CollibraGlossaryConnector`` — business glossary (Glossary/Category/BusinessTerm)
  plus ``TAGGED_WITH`` tags from columns/tables to business terms.

Run the schema connector first so the glossary connector's ``TAGGED_WITH`` edges
resolve against the Table/Column nodes it created (matched by ``collibra_id``).

Set the following environment variables before running:

    Required:
        COLLIBRA_URL         Root URL, e.g. https://myorg.collibra.com
        NEO4J_URI            Neo4j bolt URI, e.g. neo4j+s://xxx.databases.neo4j.io
        NEO4J_USERNAME       Neo4j username (default: neo4j)
        NEO4J_PASSWORD       Neo4j password

    Authentication (one of):
        COLLIBRA_TOKEN       JWT / OAuth bearer token  (preferred for production)
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

from neocarta.connectors.collibra import (
    CollibraClient,
    CollibraGlossaryConnector,
    CollibraSchemaConnector,
)


def _split_env(name: str) -> list[str] | None:
    """Parse a comma-separated env var into a list, or None when unset."""
    raw = os.environ.get(name)
    return raw.split(",") if raw else None


def main() -> None:
    """Run the Collibra → Neo4j ETL pipeline (schema, then glossary)."""
    neo4j_uri = os.environ["NEO4J_URI"]
    neo4j_user = os.environ.get("NEO4J_USERNAME", "neo4j")
    neo4j_password = os.environ["NEO4J_PASSWORD"]

    # The CollibraClient holds the URL + credentials (long-lived resources).
    client = CollibraClient(
        base_url=os.environ["COLLIBRA_URL"],
        token=os.environ.get("COLLIBRA_TOKEN"),
        username=os.environ.get("COLLIBRA_USERNAME"),
        password=os.environ.get("COLLIBRA_PASSWORD"),
    )

    # Per-call scope filters are passed to .ingest().
    community_ids = _split_env("COLLIBRA_COMMUNITY_IDS")
    domain_ids = _split_env("COLLIBRA_DOMAIN_IDS")

    with GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password)) as driver:
        CollibraSchemaConnector(client=client, neo4j_driver=driver).ingest(
            community_ids=community_ids, domain_ids=domain_ids
        )
        CollibraGlossaryConnector(client=client, neo4j_driver=driver).ingest(
            community_ids=community_ids, domain_ids=domain_ids
        )

    print("Collibra ingestion complete.")


if __name__ == "__main__":
    main()
