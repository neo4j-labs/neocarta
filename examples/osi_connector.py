"""
OSI Connector Example.

Bidirectional integration with the
[Open Semantic Interchange (OSI)](https://github.com/open-semantic-interchange/OSI)
spec. This example:

1. Ingests an OSI semantic model from the upstream TPC-DS sample YAML (fetched
   over HTTPS) into Neo4j.
2. Exports the same model back out to a local OSI YAML file, demonstrating the
   round-trip.

The connector accepts a local filesystem path or an ``http(s)://`` URL as the
ingest source. Export always writes to a local path.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

from neocarta.connectors.osi import OsiConnector

# Upstream OSI sample — a TPC-DS-flavored semantic model. Use the raw URL
# (``raw.githubusercontent.com``)
TPCDS_OSI_URL = (
    "https://raw.githubusercontent.com/open-semantic-interchange/OSI/"
    "osi-0.1.1-rc1/examples/tpcds_semantic_model.yaml"
)


def main() -> None:
    """Ingest the TPC-DS OSI sample and export it back out."""
    load_dotenv()

    neo4j_driver = GraphDatabase.driver(
        uri=os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
    )
    neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")

    connector = OsiConnector(neo4j_driver=neo4j_driver, database_name=neo4j_database)

    # Ingest from the upstream URL. A local filesystem path (str or Path) also works.
    connector.ingest(TPCDS_OSI_URL)

    # Export the ingested semantic model back to an OSI YAML file.
    output_path = Path("tpcds_export.yaml")
    connector.export(
        semantic_model_name="tpcds_retail_model",
        output_path=output_path,
    )
    print(f"Exported OSI YAML to {output_path.resolve()}")

    neo4j_driver.close()


if __name__ == "__main__":
    main()
