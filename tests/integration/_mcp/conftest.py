"""Pytest fixtures for MCP server integration tests."""

import random
import shutil
import tempfile
from pathlib import Path

import pytest
from neo4j import GraphDatabase

from neocarta.connectors.csv import CSVConnector
from neocarta.connectors.osi import OsiConnector
from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector
from neocarta.enums import NodeLabel

DATABASE_NAME = "neo4j"

#: The sample OSI semantic model shipped with the repo, loaded by the OSI fixtures.
OSI_SEMANTIC_MODEL_PATH = (
    Path(__file__).resolve().parents[3] / "datasets" / "osi" / "acme_semantic_model.yaml"
)

# Fixed-seed random vector reused for every input so that cosine similarity
# between stored node embeddings and query embeddings is always 1.0.
_rng = random.Random(42)  # noqa: S311
_MOCK_EMBEDDING: list[float] = [_rng.random() for _ in range(768)]


class MockEmbeddingsConnector(LiteLLMEmbeddingsConnector):
    """Embedder that returns a fixed random vector without calling any provider.

    Using the same vector for both stored embeddings and query embeddings
    gives a cosine similarity of 1.0, ensuring results pass the > 0.5
    threshold used by the MCP similarity tools.
    """

    def __init__(self, neo4j_driver, database_name: str = DATABASE_NAME) -> None:
        super().__init__(
            neo4j_driver=neo4j_driver,
            database_name=database_name,
        )

    def _create_embedding_sync(self, description: str) -> list[float]:  # noqa: ARG002
        return list(_MOCK_EMBEDDING)

    async def _create_embedding_async(self, description: str) -> list[float]:  # noqa: ARG002
        return list(_MOCK_EMBEDDING)

    def _create_embeddings_sync(self, descriptions: list[str]) -> list[list[float]]:
        return [list(_MOCK_EMBEDDING) for _ in descriptions]

    async def _create_embeddings_async(self, descriptions: list[str]) -> list[list[float]]:
        return [list(_MOCK_EMBEDDING) for _ in descriptions]


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
    (temp_dir / "glossary_info.csv").write_text(
        "glossary_name,name,description\n"
        "test_glossary,Test Glossary,Glossary for MCP integration tests\n"
    )
    (temp_dir / "category_info.csv").write_text(
        "glossary_name,category_name,name,description\n"
        "test_glossary,sales_metrics,Sales Metrics,Metrics for sales\n"
        "test_glossary,customer_metrics,Customer Metrics,Metrics for customers\n"
    )
    (temp_dir / "business_term_info.csv").write_text(
        "glossary_name,category_name,term_name,description\n"
        "test_glossary,sales_metrics,Order Total,Total monetary amount of an order\n"
        "test_glossary,customer_metrics,Customer Name,Full name of a customer\n"
    )
    (temp_dir / "table_term_info.csv").write_text(
        "database_name,schema_name,table_name,glossary_name,category_name,term_name\n"
        "my-project,sales,orders,test_glossary,sales_metrics,Order Total\n"
        "my-project,sales,customers,test_glossary,customer_metrics,Customer Name\n"
    )
    (temp_dir / "column_term_info.csv").write_text(
        "database_name,schema_name,table_name,column_name,glossary_name,category_name,term_name\n"
        "my-project,sales,orders,total,test_glossary,sales_metrics,Order Total\n"
        "my-project,sales,customers,name,test_glossary,customer_metrics,Customer Name\n"
    )

    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture(scope="module")
def loaded_graph(setup, sample_csv_dir):
    """Load sample graph data and write mock embeddings once for the module.

    The fixture owns the Neo4j driver and closes it after setup, including
    setup failures.
    """
    sync_driver = GraphDatabase.driver(
        setup.get_connection_url(),
        auth=(setup.username, setup.password),
    )

    try:
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

    finally:
        sync_driver.close()


@pytest.fixture(scope="module")
def osi_loaded_graph(setup):
    """Load the sample OSI semantic model and write mock metric embeddings once per module.

    Ingests ``datasets/osi/acme_semantic_model.yaml`` via the OSI connector — which creates
    the Domain/Table/Column/Metric/BusinessTerm full-text indexes — then writes mock
    embeddings (creating the vector indexes) for the Metric, Table, and Column labels. With
    full-text + vector indexes and the synonyms-derived BusinessTerm nodes present, the
    metric/table/column search tools register at the top business-term-bridged hybrid tier,
    and the table/column hits surface the OSI expression/aspect enrichment. The fixture owns
    the Neo4j driver and closes it after setup, including setup failures.
    """
    sync_driver = GraphDatabase.driver(
        setup.get_connection_url(),
        auth=(setup.username, setup.password),
    )

    try:
        with sync_driver.session(database=DATABASE_NAME) as session:
            session.run("MATCH (n) DETACH DELETE n")

        OsiConnector(
            neo4j_driver=sync_driver,
            database_name=DATABASE_NAME,
        ).ingest(OSI_SEMANTIC_MODEL_PATH)

        MockEmbeddingsConnector(
            neo4j_driver=sync_driver,
            database_name=DATABASE_NAME,
        ).run(node_labels=[NodeLabel.METRIC, NodeLabel.TABLE, NodeLabel.COLUMN])

    finally:
        sync_driver.close()


@pytest.fixture(scope="module")
def neo4j_connection(setup):
    """Return Neo4j connection parameters for use inside async test helpers."""
    return {
        "uri": setup.get_connection_url(),
        "username": setup.username,
        "password": setup.password,
    }
