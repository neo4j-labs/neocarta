"""
BigQuery Query Logs Connector Example.

This example demonstrates how to extract query logs from BigQuery,
parse the SQL queries to extract table and column references,
and load the metadata into Neo4j for analysis.

Usage:
    # Extract last 30 days of query logs with embeddings
    python examples/bigquery_logs.py

    # Extract specific time range
    python examples/bigquery_logs.py --start-date "2024-01-01" --end-date "2024-01-31"

    # Skip embeddings
    python examples/bigquery_logs.py --skip-embeddings

    # Increase query limit
    python examples/bigquery_logs.py --limit 500

Environment Variables Required:
    - NEO4J_URI: Neo4j connection URI
    - NEO4J_USERNAME: Neo4j username
    - NEO4J_PASSWORD: Neo4j password
    - NEO4J_DATABASE: Neo4j database name (optional, defaults to 'neo4j')
    - GCP_PROJECT_ID: Google Cloud Project ID
    - BIGQUERY_DATASET_ID: BigQuery dataset to extract logs for
    - BIGQUERY_REGION: BigQuery region (optional, defaults to 'region-us')
    - OPENAI_API_KEY: OpenAI API key for embeddings (if using embeddings)
"""

import argparse
import asyncio
import os

from dotenv import load_dotenv
from google.cloud import bigquery
from neo4j import GraphDatabase

from neocarta.connectors.bigquery import BigQueryLogsConnector


async def main(
    start_timestamp: str | None = None,
    end_timestamp: str | None = None,
    limit: int = 100,
    region: str = "region-us",
    drop_failed_queries: bool = True,
) -> None:
    """Run the BigQuery query log connector to load query logs from BigQuery."""
    load_dotenv()
    print("Starting BigQuery Logs connector...")

    # Create clients and drivers
    print("Creating drivers and clients...")
    neo4j_driver = GraphDatabase.driver(
        uri=os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
    )
    neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")
    bigquery_client = bigquery.Client(project=os.getenv("GCP_PROJECT_ID"))

    print("Extracting query logs from BigQuery...")
    if start_timestamp and end_timestamp:
        print(f"  Time range: {start_timestamp} to {end_timestamp}")
    else:
        print("  Time range: Last 30 days (default)")
    print(f"  Dataset: {os.getenv('BIGQUERY_DATASET_ID')}")
    print(f"  Region: {region}")
    print(f"  Limit: {limit} queries")
    print(f"  Drop failed queries: {drop_failed_queries}")

    # Extract, transform, and load BigQuery query logs into Neo4j
    bigquery_logs_connector = BigQueryLogsConnector(
        client=bigquery_client,
        project_id=os.getenv("GCP_PROJECT_ID"),
        neo4j_driver=neo4j_driver,
        database_name=neo4j_database,
    )

    bigquery_logs_connector.run(
        dataset_id=os.getenv("BIGQUERY_DATASET_ID"),
        region=region,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        limit=limit,
        drop_failed_queries=drop_failed_queries,
    )

    print("\nQuery logs loaded into Neo4j!")
    print(f"  Queries: {len(bigquery_logs_connector.extractor.query_info)}")
    print(f"  Tables referenced: {len(bigquery_logs_connector.extractor.table_info)}")
    print(f"  Columns referenced: {len(bigquery_logs_connector.extractor.column_info)}")

    print("\nConnector completed successfully!")
    print("\nNext steps:")
    print("  - Query Neo4j to analyze query patterns")
    print("  - Identify frequently used tables and columns")
    print("  - Analyze join relationships between tables")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract BigQuery query logs and load into Neo4j",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract last 30 days with embeddings (default)
  python examples/bigquery_logs.py

  # Extract specific date range
  python examples/bigquery_logs.py --start-date "2024-01-01 00:00:00" --end-date "2024-01-31 23:59:59"

  # Extract more queries without embeddings
  python examples/bigquery_logs.py --limit 500 --skip-embeddings

  # Include failed queries for debugging
  python examples/bigquery_logs.py --include-failed-queries
        """,
    )

    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start timestamp (ISO format: 'YYYY-MM-DD HH:MM:SS'). Defaults to 30 days ago.",
    )

    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End timestamp (ISO format: 'YYYY-MM-DD HH:MM:SS'). Defaults to now.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of queries to extract (default: 100)",
    )

    parser.add_argument(
        "--region",
        type=str,
        default=os.getenv("BIGQUERY_REGION", "region-us"),
        help="BigQuery region for JOBS_BY_PROJECT (default: region-us)",
    )

    parser.add_argument(
        "--include-failed-queries",
        action="store_true",
        help="Include failed queries in the extraction (default: exclude failed queries)",
    )

    args = parser.parse_args()

    asyncio.run(
        main(
            start_timestamp=args.start_date,
            end_timestamp=args.end_date,
            limit=args.limit,
            region=args.region,
            drop_failed_queries=not args.include_failed_queries,
        )
    )
