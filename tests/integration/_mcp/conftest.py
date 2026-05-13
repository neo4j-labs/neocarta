"""Pytest fixtures for MCP server integration tests."""

import random
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from neo4j import GraphDatabase

from neocarta.connectors.csv import CSVConnector
from neocarta.enrichment.embeddings import OpenAIEmbeddingsConnector
from neocarta.enums import NodeLabel

DATABASE_NAME = "neo4j"

# Fixed-seed random vector reused for every input so that cosine similarity
# between stored node embeddings and query embeddings is always 1.0.
_rng = random.Random(42)  # noqa: S311
_MOCK_EMBEDDING: list[float] = [_rng.random() for _ in range(768)]


class MockEmbeddingsConnector(OpenAIEmbeddingsConnector):
    """Embedder that returns a fixed random vector without calling OpenAI.

    Using the same vector for both stored embeddings and query embeddings
    gives a cosine similarity of 1.0, ensuring results pass the > 0.5
    threshold used by the MCP similarity tools.
    """

    def __init__(self, neo4j_driver, database_name: str = DATABASE_NAME) -> None:
        super().__init__(
            neo4j_driver=neo4j_driver,
            client=MagicMock(),
            database_name=database_name,
        )

    def _create_embedding_sync(self, description: str) -> list[float]:  # noqa: ARG002
        return list(_MOCK_EMBEDDING)

    async def _create_embedding_async(self, description: str) -> list[float]:  # noqa: ARG002
        return list(_MOCK_EMBEDDING)


@pytest.fixture(scope="module")
def sample_csv_dir(setup):
    """Create a temporary directory with sample graph data CSVs."""
    temp_dir = Path(tempfile.mkdtemp())

    (temp_dir / "database_info.csv").write_text(
        "database_name,platform,service,description\nmy-project,GCP,BIGQUERY,Test database\n"
    )
    (temp_dir / "schema_info.csv").write_text(
        "database_name,schema_name,description\n"
        "my-project,sales,Sales schema containing orders and customer records\n"
        "my-project,analytics,Analytics schema for reporting and aggregated metrics\n"
    )
    (temp_dir / "table_info.csv").write_text(
        "database_name,schema_name,table_name,description\n"
        "my-project,sales,orders,Orders placed by customers including totals and dates\n"
        "my-project,sales,customers,Customer master table with names and contact information\n"
        "my-project,analytics,summary,Summary reporting table for aggregated business metrics\n"
    )
    (temp_dir / "column_info.csv").write_text(
        "database_name,schema_name,table_name,column_name,data_type,"
        "is_nullable,is_primary_key,is_foreign_key,description\n"
        "my-project,sales,orders,order_id,STRING,false,true,false,"
        "Unique identifier for the order\n"
        "my-project,sales,orders,customer_id,STRING,false,false,true,"
        "Foreign key reference to the customers table\n"
        "my-project,sales,orders,total,FLOAT64,true,false,false,"
        "Total order amount in USD\n"
        "my-project,sales,customers,customer_id,STRING,false,true,false,"
        "Unique identifier for the customer\n"
        "my-project,sales,customers,name,STRING,false,false,false,"
        "Full name of the customer\n"
        "my-project,analytics,summary,metric_value,FLOAT64,true,false,false,"
        "Aggregated metric value for reporting\n"
    )
    (temp_dir / "column_references_info.csv").write_text(
        "source_database_name,source_schema_name,source_table_name,source_column_name,"
        "target_database_name,target_schema_name,target_table_name,target_column_name,criteria\n"
        "my-project,sales,orders,customer_id,my-project,sales,customers,customer_id,"
        "orders.customer_id = customers.customer_id\n"
    )
    (temp_dir / "value_info.csv").write_text(
        "database_name,schema_name,table_name,column_name,value\n"
        "my-project,sales,customers,name,John Doe\n"
        "my-project,sales,customers,name,Jane Smith\n"
        "my-project,sales,customers,name,Bob Johnson\n"
    )

    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture(scope="module")
def loaded_graph(setup, sample_csv_dir):
    """Load sample graph data and write mock embeddings once for the module.

    The fixture owns the Neo4j driver and closes it after setup.
    """
    sync_driver = GraphDatabase.driver(
        setup.get_connection_url(),
        auth=(setup.username, setup.password),
    )

    with sync_driver.session(database=DATABASE_NAME) as session:
        session.run("MATCH (n) DETACH DELETE n")

    CSVConnector(
        csv_directory=str(sample_csv_dir),
        neo4j_driver=sync_driver,
        database_name=DATABASE_NAME,
    ).run()

    MockEmbeddingsConnector(
        neo4j_driver=sync_driver,
        database_name=DATABASE_NAME,
    ).run(node_labels=[NodeLabel.SCHEMA, NodeLabel.TABLE, NodeLabel.COLUMN])

    sync_driver.close()


@pytest.fixture(scope="module")
def neo4j_connection(setup):
    """Return Neo4j connection parameters for use inside async test helpers."""
    return {
        "uri": setup.get_connection_url(),
        "username": setup.username,
        "password": setup.password,
    }
