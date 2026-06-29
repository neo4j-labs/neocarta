"""Example: load Databricks Unity Catalog schema metadata into Neo4j.

Reads structural metadata (Database/Schema/Table/Column/Value + HAS_*/REFERENCES)
from a catalog's ``<catalog>.information_schema.*`` views over a Databricks SQL
warehouse using the in-process ``databricks-sql-connector`` (DB-API) — no Spark,
no JDBC. Mirrors the BigQuery schema connector: one schema per ``ingest()`` call.

Requires the ``databricks`` extra: ``pip install neocarta[databricks]`` (or
``uv sync --all-extras``). Set in ``.env``:

* ``DATABRICKS_SERVER_HOSTNAME`` — e.g. ``dbc-xxxx.cloud.databricks.com``
* ``DATABRICKS_HTTP_PATH``       — SQL warehouse HTTP path, e.g. ``/sql/1.0/warehouses/abc123``
* ``DATABRICKS_TOKEN``           — personal access token (PAT)
* ``DATABRICKS_CATALOG`` / ``DATABRICKS_SCHEMA`` — the catalog (Database) and schema to ingest
* ``NEO4J_URI`` / ``NEO4J_USERNAME`` / ``NEO4J_PASSWORD`` / ``NEO4J_DATABASE``
"""

import argparse
import os

from databricks import sql
from dotenv import load_dotenv
from neo4j import GraphDatabase

from neocarta import NodeLabel
from neocarta.connectors.databricks import DatabricksSchemaConnector
from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector


def main(
    schema: str | None = None,
    catalog: str | None = None,
    with_embeddings: bool = True,
    value_sample_limit: int = 10,
) -> None:
    """Run the Databricks schema connector and optionally compute embeddings."""
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

    # The caller builds and owns the connection (mirroring the BigQuery client);
    # the connector never closes it. Use it as a context manager so it is released.
    with sql.connect(
        server_hostname=os.getenv("DATABRICKS_SERVER_HOSTNAME"),
        http_path=os.getenv("DATABRICKS_HTTP_PATH"),
        access_token=os.getenv("DATABRICKS_TOKEN"),
    ) as connection:
        print(f"Ingesting Databricks schema metadata for {catalog}.{schema} into Neo4j...")
        DatabricksSchemaConnector(
            connection=connection,
            catalog=catalog,
            neo4j_driver=neo4j_driver,
            database_name=neo4j_database,
            value_sample_limit=value_sample_limit,
        ).ingest(schema=schema)

    if with_embeddings:
        print("Generating embeddings for Database/Schema/Table/Column nodes...")
        # Configure provider via env vars (e.g. OPENAI_API_KEY, GEMINI_API_KEY).
        embeddings = LiteLLMEmbeddingsConnector(
            neo4j_driver=neo4j_driver,
            embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            database_name=neo4j_database,
        )
        embeddings.run(
            node_labels=[NodeLabel.DATABASE, NodeLabel.SCHEMA, NodeLabel.TABLE, NodeLabel.COLUMN]
        )

    print("Connector completed successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Ingest Databricks Unity Catalog schema metadata (Database/Schema/Table/Column/Value) "
            "over a SQL warehouse into Neo4j. Embeddings enabled by default."
        )
    )
    parser.add_argument("--catalog", default=None, help="Catalog (overrides DATABRICKS_CATALOG).")
    parser.add_argument("--schema", default=None, help="Schema (overrides DATABRICKS_SCHEMA).")
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Skip embedding generation (only load metadata into Neo4j).",
    )
    parser.add_argument(
        "--no-value-sampling",
        action="store_true",
        help="Skip sample-value reads (no :Value nodes; avoids reading table data).",
    )
    args = parser.parse_args()

    main(
        schema=args.schema,
        catalog=args.catalog,
        with_embeddings=not args.skip_embeddings,
        value_sample_limit=0 if args.no_value_sampling else 10,
    )
