"""Shared fixtures for OSI connector unit tests."""

from pathlib import Path

import pytest
import yaml

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def tpcds_yaml_path() -> Path:
    """Filesystem path to the TPC-DS OSI sample (downloaded once from the OSI repo)."""
    return FIXTURE_DIR / "tpcds_osi.yaml"


@pytest.fixture
def tpcds_spec(tpcds_yaml_path: Path) -> dict:
    """The parsed TPC-DS OSI spec dict."""
    return yaml.safe_load(tpcds_yaml_path.read_text(encoding="utf-8"))


@pytest.fixture
def minimal_spec() -> dict:
    """
    A minimal but complete OSI spec exercising the major shapes:
    - 3-part source (db.schema.table)
    - ai_context as a YAML dict with synonyms
    - Relationship with paired columns
    - Metric with expression
    """
    return {
        "version": "0.2.0",
        "semantic_model": [
            {
                "name": "sales_model",
                "description": "Test semantic model",
                "ai_context": {"instructions": "Test instructions"},
                "datasets": [
                    {
                        "name": "orders",
                        "source": "warehouse.public.orders",
                        "primary_key": ["order_id"],
                        "unique_keys": [["order_id"], ["customer_id", "order_date"]],
                        "description": "Order facts",
                        "ai_context": {"synonyms": ["sales", "transactions"]},
                        "fields": [
                            {
                                "name": "order_id",
                                "expression": {
                                    "dialects": [
                                        {"dialect": "ANSI_SQL", "expression": "order_id"}
                                    ]
                                },
                                "description": "Primary key",
                            },
                            {
                                "name": "customer_id",
                                "expression": {
                                    "dialects": [
                                        {"dialect": "ANSI_SQL", "expression": "customer_id"}
                                    ]
                                },
                                "description": "FK to customer",
                            },
                            {
                                "name": "order_date",
                                "expression": {
                                    "dialects": [
                                        {"dialect": "ANSI_SQL", "expression": "order_date"}
                                    ]
                                },
                                "dimension": {"is_time": True},
                                "label": "filter",
                            },
                        ],
                    },
                    {
                        "name": "customers",
                        "source": "warehouse.public.customers",
                        "primary_key": ["customer_id"],
                        "fields": [
                            {
                                "name": "customer_id",
                                "expression": {
                                    "dialects": [
                                        {"dialect": "ANSI_SQL", "expression": "customer_id"}
                                    ]
                                },
                            },
                        ],
                    },
                ],
                "relationships": [
                    {
                        "name": "orders_to_customers",
                        "from": "orders",
                        "to": "customers",
                        "from_columns": ["customer_id"],
                        "to_columns": ["customer_id"],
                    }
                ],
                "metrics": [
                    {
                        "name": "total_revenue",
                        "expression": {
                            "dialects": [
                                {"dialect": "ANSI_SQL", "expression": "SUM(orders.amount)"}
                            ]
                        },
                        "description": "Sum of order amounts",
                        "ai_context": {"synonyms": ["revenue"]},
                    }
                ],
            }
        ],
    }


@pytest.fixture
def query_source_spec() -> dict:
    """OSI spec where the dataset source is a SQL query rather than a dotted identifier."""
    return {
        "version": "0.2.0",
        "semantic_model": [
            {
                "name": "query_model",
                "datasets": [
                    {
                        "name": "active_customers",
                        "source": "SELECT * FROM customers WHERE active = true",
                        "fields": [
                            {
                                "name": "customer_id",
                                "expression": {
                                    "dialects": [
                                        {"dialect": "ANSI_SQL", "expression": "customer_id"}
                                    ]
                                },
                            },
                        ],
                    }
                ],
            }
        ],
    }
