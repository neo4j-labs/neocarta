"""Example: load Snowflake schema metadata into Neo4j.

Reads structural metadata (Database/Schema/Table/Column/Value + HAS_*/REFERENCES)
from a database's ``<database>.INFORMATION_SCHEMA.*`` views (and ``SHOW ... KEYS``
for primary/foreign keys) over the in-process ``snowflake-connector-python``
(DB-API) — no Spark, no JDBC. Mirrors the BigQuery schema connector: one schema
per ``ingest()`` call.

Requires the ``snowflake`` extra: ``pip install neocarta[snowflake]`` (or
``uv sync --all-extras``). Set in ``.env``:

* ``SNOWFLAKE_ACCOUNT``   — e.g. ``xy12345.us-east-1``
* ``SNOWFLAKE_USER`` / ``SNOWFLAKE_PASSWORD``
* ``SNOWFLAKE_WAREHOUSE`` — warehouse used to run the metadata queries
* ``SNOWFLAKE_ROLE``      — role to assume (optional)
* ``SNOWFLAKE_DATABASE`` / ``SNOWFLAKE_SCHEMA`` — the database (Database) and schema to ingest
* ``NEO4J_URI`` / ``NEO4J_USERNAME`` / ``NEO4J_PASSWORD`` / ``NEO4J_DATABASE``
"""

import argparse
import os

import snowflake.connector
from dotenv import load_dotenv
from neo4j import GraphDatabase

from neocarta import NodeLabel
from neocarta.connectors.snowflake import SnowflakeSchemaConnector
from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector


def main(
    schema: str | None = None,
    database: str | None = None,
    with_embeddings: bool = True,
    value_sample_limit: int = 10,
) -> None:
    """Run the Snowflake schema connector and optionally compute embeddings."""
    load_dotenv()
    database = database or os.getenv("SNOWFLAKE_DATABASE")
    schema = schema or os.getenv("SNOWFLAKE_SCHEMA")
    if not database or not schema:
        raise SystemExit(
            "Set SNOWFLAKE_DATABASE and SNOWFLAKE_SCHEMA (or pass --database / --schema)."
        )

    print("Creating Neo4j driver and Snowflake connection...")
    neo4j_driver = GraphDatabase.driver(
        uri=os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
    )
    neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")

    # Close both client pools unconditionally — an error during ingest or embeddings
    # must not leak the Neo4j driver or the Snowflake connection. The connector never
    # closes the connection itself (the caller owns it, mirroring the BigQuery client).
    try:
        with snowflake.connector.connect(
            account=os.getenv("SNOWFLAKE_ACCOUNT"),
            user=os.getenv("SNOWFLAKE_USER"),
            password=os.getenv("SNOWFLAKE_PASSWORD"),
            warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
            role=os.getenv("SNOWFLAKE_ROLE"),
            database=database,
        ) as connection:
            print(f"Ingesting Snowflake schema metadata for {database}.{schema} into Neo4j...")
            SnowflakeSchemaConnector(
                connection=connection,
                database=database,
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
                node_labels=[
                    NodeLabel.DATABASE,
                    NodeLabel.SCHEMA,
                    NodeLabel.TABLE,
                    NodeLabel.COLUMN,
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
            "Ingest Snowflake schema metadata (Database/Schema/Table/Column/Value) over a "
            "warehouse into Neo4j. Embeddings enabled by default."
        )
    )
    parser.add_argument("--database", default=None, help="Database (overrides SNOWFLAKE_DATABASE).")
    parser.add_argument("--schema", default=None, help="Schema (overrides SNOWFLAKE_SCHEMA).")
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
        database=args.database,
        with_embeddings=not args.skip_embeddings,
        value_sample_limit=0 if args.no_value_sampling else 10,
    )
