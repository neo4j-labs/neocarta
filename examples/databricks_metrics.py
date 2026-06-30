"""Example: load Databricks Unity Catalog metric views into Neo4j.

Discovers metric views (Business Semantics) from a catalog's
``<catalog>.information_schema.tables`` (``table_type = 'METRIC_VIEW'``) and reads
each one's YAML definition (via ``DESCRIBE TABLE EXTENDED … AS JSON``) over a
Databricks SQL warehouse using the in-process ``databricks-sql-connector``
(DB-API) — no Spark, no JDBC — and maps them onto the OSI semantic-model nodes
(OsiSemanticModel / OsiTable / OsiColumn / Metric / Expression / OsiAiContext).
One schema per ``ingest()`` call.

Requires the ``databricks`` extra: ``pip install neocarta[databricks]`` (or
``uv sync --all-extras``). Set in ``.env``:

* ``DATABRICKS_SERVER_HOSTNAME`` — e.g. ``dbc-xxxx.cloud.databricks.com``
* ``DATABRICKS_HTTP_PATH``       — SQL warehouse HTTP path, e.g. ``/sql/1.0/warehouses/abc123``
* ``DATABRICKS_TOKEN``           — personal access token (PAT)
* ``DATABRICKS_CATALOG`` / ``DATABRICKS_SCHEMA`` — the catalog and schema to scan
* ``NEO4J_URI`` / ``NEO4J_USERNAME`` / ``NEO4J_PASSWORD`` / ``NEO4J_DATABASE``
"""

import argparse
import os

from databricks import sql
from dotenv import load_dotenv
from neo4j import GraphDatabase

from neocarta import NodeLabel
from neocarta.connectors.databricks import DatabricksMetricsConnector
from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector


def main(
    schema: str | None = None,
    catalog: str | None = None,
    with_embeddings: bool = True,
) -> None:
    """Run the Databricks metrics connector and optionally compute embeddings."""
    load_dotenv()
    catalog = catalog or os.getenv("DATABRICKS_CATALOG")
    schema = schema or os.getenv("DATABRICKS_SCHEMA")
    if not catalog or not schema:
        raise SystemExit(
            "Set DATABRICKS_CATALOG and DATABRICKS_SCHEMA (or pass --catalog / --schema)."
        )

    print("Creating Neo4j driver and Databricks SQL connection...")
    neo4j_driver = GraphDatabase.driver(
        uri=os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
    )
    neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")

    # Close both client pools unconditionally — an error during ingest or embeddings
    # must not leak the Neo4j driver or the Databricks connection. The connector never
    # closes the connection itself (the caller owns it, mirroring the BigQuery client).
    try:
        with sql.connect(
            server_hostname=os.getenv("DATABRICKS_SERVER_HOSTNAME"),
            http_path=os.getenv("DATABRICKS_HTTP_PATH"),
            access_token=os.getenv("DATABRICKS_TOKEN"),
        ) as connection:
            print(f"Ingesting Databricks metric views for {catalog}.{schema} into Neo4j...")
            DatabricksMetricsConnector(
                connection=connection,
                catalog=catalog,
                neo4j_driver=neo4j_driver,
                database_name=neo4j_database,
            ).ingest(schema=schema)

        if with_embeddings:
            print("Generating embeddings for Domain/Table/Column/Metric nodes...")
            # Configure provider via env vars (e.g. OPENAI_API_KEY, GEMINI_API_KEY).
            embeddings = LiteLLMEmbeddingsConnector(
                neo4j_driver=neo4j_driver,
                embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
                database_name=neo4j_database,
            )
            embeddings.run(
                node_labels=[
                    NodeLabel.DOMAIN,
                    NodeLabel.TABLE,
                    NodeLabel.COLUMN,
                    NodeLabel.METRIC,
                ]
            )

    finally:
        neo4j_driver.close()

    # Only report success after cleanup finishes, so a close() failure isn't
    # hidden behind a "completed successfully" message.
    print("Connector completed successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Ingest Databricks Unity Catalog metric views (Business Semantics) over a SQL "
            "warehouse into Neo4j as OSI semantic-model nodes. Embeddings enabled by default."
        )
    )
    parser.add_argument("--catalog", default=None, help="Catalog (overrides DATABRICKS_CATALOG).")
    parser.add_argument("--schema", default=None, help="Schema (overrides DATABRICKS_SCHEMA).")
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Skip embedding generation (only load metric-view metadata into Neo4j).",
    )
    args = parser.parse_args()

    main(
        schema=args.schema,
        catalog=args.catalog,
        with_embeddings=not args.skip_embeddings,
    )
