"""
OSI Connector Example.

Bidirectional integration with the
[Open Semantic Interchange (OSI)](https://github.com/open-semantic-interchange/OSI)
spec. This example:

1. Ingests an OSI semantic model (either the local ACME sample or the upstream
   TPC-DS sample fetched over HTTPS) into Neo4j.
2. Exports the ingested model back out to a local OSI YAML file to demonstrate
   the round-trip.

The connector accepts a local filesystem path or an ``http(s)://`` URL as the
ingest source. Export always writes to a local path.

Usage:

    uv run examples/osi_connector.py                # acme (default, local file)
    uv run examples/osi_connector.py --sample tpcds # TPC-DS (fetched from upstream)
"""

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

from neocarta.connectors.osi import OsiConnector

# Local ACME sample — the 33-table semantic model in datasets/osi/.
ACME_OSI_PATH = Path(__file__).resolve().parent.parent / "datasets" / "osi" / "acme_semantic_model.yaml"

# Upstream OSI sample — a TPC-DS-flavored semantic model.
# Use the raw URL (``raw.githubusercontent.com``).
TPCDS_OSI_URL = (
    "https://raw.githubusercontent.com/open-semantic-interchange/OSI/"
    "osi-0.1.1-rc1/examples/tpcds_semantic_model.yaml"
)

SAMPLES = {
    "acme": (ACME_OSI_PATH, "acme_corp_model"),
    "tpcds": (TPCDS_OSI_URL, "tpcds_retail_model"),
}


def main(sample: str) -> None:
    """Ingest the chosen OSI sample and export it back out."""
    load_dotenv()

    source, semantic_model_name = SAMPLES[sample]

    neo4j_driver = GraphDatabase.driver(
        uri=os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
    )
    neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")

    connector = OsiConnector(neo4j_driver=neo4j_driver, database_name=neo4j_database)

    # Ingest accepts either a local filesystem path (Path or str) or an HTTP(S) URL.
    connector.ingest(source)

    # Export the ingested semantic model back to an OSI YAML file.
    output_path = Path(f"{sample}_export.yaml")
    connector.export(
        semantic_model_name=semantic_model_name,
        output_path=output_path,
    )
    print(f"Exported OSI YAML to {output_path.resolve()}")

    neo4j_driver.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest an OSI YAML sample into Neo4j and export it back out."
    )
    parser.add_argument(
        "--sample",
        choices=sorted(SAMPLES.keys()),
        default="acme",
        help="Which OSI sample to load: 'acme' (local) or 'tpcds' (upstream URL). Default: acme.",
    )
    args = parser.parse_args()
    main(args.sample)
