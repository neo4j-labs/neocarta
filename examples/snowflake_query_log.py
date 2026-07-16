"""Example: load Snowflake query-log lineage into Neo4j.

Reads query history from ``SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY`` over the
in-process ``snowflake-connector-python`` (DB-API), parses each statement with
``sqlglot`` (``read="snowflake"``), and loads ``Query`` / ``CTE`` nodes plus the
``USES_TABLE`` / ``USES_COLUMN`` / ``DEFINES`` edges (and the RDBMS scaffolding
they reference). Mirrors the BigQuery logs connector; only the source differs.

Reading ``ACCOUNT_USAGE`` needs access to the shared ``SNOWFLAKE`` database
(``GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE ...``) and has ingest latency.

Requires the ``snowflake`` extra: ``pip install neocarta[snowflake]``. Set in
``.env`` the ``SNOWFLAKE_*`` and ``NEO4J_*`` variables (see ``snowflake_schema.py``).
"""

import argparse
import os

import snowflake.connector
from dotenv import load_dotenv
from neo4j import GraphDatabase

from neocarta.connectors.snowflake import SnowflakeLogsConnector


def main(
    schema: str | None = None,
    database: str | None = None,
    start_timestamp: str | None = None,
    end_timestamp: str | None = None,
    limit: int = 100,
) -> None:
    """Run the Snowflake logs connector over ACCOUNT_USAGE.QUERY_HISTORY."""
    load_dotenv()
    database = database or os.getenv("SNOWFLAKE_DATABASE")
    schema = schema or os.getenv("SNOWFLAKE_SCHEMA")
    if not database:
        raise SystemExit("Set SNOWFLAKE_DATABASE (or pass --database).")

    print("Creating Neo4j driver and Snowflake connection...")
    neo4j_driver = GraphDatabase.driver(
        uri=os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
    )
    neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")

    try:
        with snowflake.connector.connect(
            account=os.getenv("SNOWFLAKE_ACCOUNT"),
            user=os.getenv("SNOWFLAKE_USER"),
            password=os.getenv("SNOWFLAKE_PASSWORD"),
            warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
            role=os.getenv("SNOWFLAKE_ROLE"),
            database=database,
        ) as connection:
            print(f"Ingesting Snowflake query logs for {database} into Neo4j...")
            SnowflakeLogsConnector(
                connection=connection,
                database=database,
                neo4j_driver=neo4j_driver,
                database_name=neo4j_database,
            ).ingest(
                schema=schema,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                limit=limit,
            )
    finally:
        neo4j_driver.close()

    print("Connector completed successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Ingest Snowflake query-log lineage (Query/CTE + USES_TABLE/USES_COLUMN/DEFINES) "
            "from ACCOUNT_USAGE.QUERY_HISTORY into Neo4j."
        )
    )
    parser.add_argument("--database", default=None, help="Database (overrides SNOWFLAKE_DATABASE).")
    parser.add_argument(
        "--schema", default=None, help="Schema to filter/resolve by (overrides SNOWFLAKE_SCHEMA)."
    )
    parser.add_argument("--start-date", default=None, help="Inclusive start timestamp (ISO 8601).")
    parser.add_argument("--end-date", default=None, help="Exclusive end timestamp (ISO 8601).")
    parser.add_argument("--limit", type=int, default=100, help="Max number of queries to extract.")
    args = parser.parse_args()

    main(
        schema=args.schema,
        database=args.database,
        start_timestamp=args.start_date,
        end_timestamp=args.end_date,
        limit=args.limit,
    )
