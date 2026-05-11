"""Pytest fixtures for CSV connector integration tests."""

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_csv_dir():
    """
    Provide a temporary directory for CSV files.

    Yields:
    ------
    Path
        Path to temporary directory
    """
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)


@pytest.fixture
def sample_database_csv(temp_csv_dir):
    """Create sample database_info.csv file."""
    csv_content = """database_name,platform,service,description
my-project,GCP,BIGQUERY,Test database
"""
    csv_path = temp_csv_dir / "database_info.csv"
    csv_path.write_text(csv_content)
    return csv_path


@pytest.fixture
def sample_schema_csv(temp_csv_dir):
    """Create sample schema_info.csv file."""
    csv_content = """database_name,schema_name,description
my-project,sales,Sales schema
my-project,analytics,Analytics schema
"""
    csv_path = temp_csv_dir / "schema_info.csv"
    csv_path.write_text(csv_content)
    return csv_path


@pytest.fixture
def sample_table_csv(temp_csv_dir):
    """Create sample table_info.csv file."""
    csv_content = """database_name,schema_name,table_name,description
my-project,sales,orders,Orders table
my-project,sales,customers,Customers table
my-project,analytics,summary,Summary table
"""
    csv_path = temp_csv_dir / "table_info.csv"
    csv_path.write_text(csv_content)
    return csv_path


@pytest.fixture
def sample_column_csv(temp_csv_dir):
    """Create sample column_info.csv file."""
    csv_content = """database_name,schema_name,table_name,column_name,data_type,is_nullable,is_primary_key,is_foreign_key,description
my-project,sales,orders,order_id,STRING,false,true,false,Order ID
my-project,sales,orders,customer_id,STRING,false,false,true,Customer ID
my-project,sales,orders,total,FLOAT64,true,false,false,Order total
my-project,sales,customers,customer_id,STRING,false,true,false,Customer ID
my-project,sales,customers,name,STRING,false,false,false,Customer name
"""
    csv_path = temp_csv_dir / "column_info.csv"
    csv_path.write_text(csv_content)
    return csv_path


@pytest.fixture
def sample_references_csv(temp_csv_dir):
    """Create sample column_references_info.csv file."""
    csv_content = """source_database_name,source_schema_name,source_table_name,source_column_name,target_database_name,target_schema_name,target_table_name,target_column_name,criteria
my-project,sales,orders,customer_id,my-project,sales,customers,customer_id,orders.customer_id = customers.customer_id
"""
    csv_path = temp_csv_dir / "column_references_info.csv"
    csv_path.write_text(csv_content)
    return csv_path


@pytest.fixture
def sample_value_csv(temp_csv_dir):
    """Create sample value_info.csv file."""
    csv_content = """database_name,schema_name,table_name,column_name,value
my-project,sales,customers,name,John Doe
my-project,sales,customers,name,Jane Smith
my-project,sales,customers,name,Bob Johnson
"""
    csv_path = temp_csv_dir / "value_info.csv"
    csv_path.write_text(csv_content)
    return csv_path


@pytest.fixture
def sample_query_csv(temp_csv_dir):
    """Create sample query_info.csv file."""
    csv_content = """query_id,content,description
q001,"SELECT * FROM sales.orders WHERE order_id = '123'",Get order by ID
q002,SELECT customer_id FROM sales.orders,Get customer IDs
"""
    csv_path = temp_csv_dir / "query_info.csv"
    csv_path.write_text(csv_content)
    return csv_path


@pytest.fixture
def sample_query_table_csv(temp_csv_dir):
    """Create sample query_table_info.csv file."""
    csv_content = """query_id,table_id
q001,my_project.sales.orders
q002,my_project.sales.orders
"""
    csv_path = temp_csv_dir / "query_table_info.csv"
    csv_path.write_text(csv_content)
    return csv_path


@pytest.fixture
def sample_query_column_csv(temp_csv_dir):
    """Create sample query_column_info.csv file."""
    csv_content = """query_id,column_id
q001,my_project.sales.orders.order_id
q002,my_project.sales.orders.customer_id
"""
    csv_path = temp_csv_dir / "query_column_info.csv"
    csv_path.write_text(csv_content)
    return csv_path


@pytest.fixture
def sample_glossary_csv(temp_csv_dir):
    """Create sample glossary_info.csv file."""
    csv_content = """glossary_name,name,description
sales_glossary,Sales Glossary,Sales business terms
"""
    csv_path = temp_csv_dir / "glossary_info.csv"
    csv_path.write_text(csv_content)
    return csv_path


@pytest.fixture
def sample_category_csv(temp_csv_dir):
    """Create sample category_info.csv file."""
    csv_content = """glossary_name,category_name,name,description
sales_glossary,metrics,Metrics,Sales metrics
"""
    csv_path = temp_csv_dir / "category_info.csv"
    csv_path.write_text(csv_content)
    return csv_path


@pytest.fixture
def sample_business_term_csv(temp_csv_dir):
    """Create sample business_term_info.csv file."""
    csv_content = """glossary_name,category_name,term_name,name,description
sales_glossary,metrics,arr,Annual Recurring Revenue,Yearly revenue
"""
    csv_path = temp_csv_dir / "business_term_info.csv"
    csv_path.write_text(csv_content)
    return csv_path


@pytest.fixture
def all_sample_csvs(
    sample_database_csv,
    sample_schema_csv,
    sample_table_csv,
    sample_column_csv,
    sample_references_csv,
    sample_value_csv,
    sample_query_csv,
    sample_query_table_csv,
    sample_query_column_csv,
    sample_glossary_csv,
    sample_category_csv,
    sample_business_term_csv,
):
    """Fixture that ensures all sample CSV files are created."""
    return {
        "database": sample_database_csv,
        "schema": sample_schema_csv,
        "table": sample_table_csv,
        "column": sample_column_csv,
        "references": sample_references_csv,
        "value": sample_value_csv,
        "query": sample_query_csv,
        "query_table": sample_query_table_csv,
        "query_column": sample_query_column_csv,
        "glossary": sample_glossary_csv,
        "category": sample_category_csv,
        "business_term": sample_business_term_csv,
    }
