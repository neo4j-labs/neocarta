"""Utility functions for generating hierarchical IDs for graph entities."""

import hashlib
from typing import Any


def _normalize(s: str) -> str:
    """Normalize an ID segment: lowercase, spaces → _, hyphens → _."""
    return s.lower().replace(" ", "_").replace("-", "_")


def generate_database_id(database: str) -> str:
    """
    Generate a database ID.

    Parameters
    ----------
    database : str
        The database identifier (name or ID)

    Returns:
    -------
    str
        The database ID

    Examples:
    --------
    >>> generate_database_id("my-project")
    'my_project'
    """
    return _normalize(database)


def generate_schema_id(database: str, schema: str) -> str:
    """
    Generate a schema ID from database and schema identifiers.

    Parameters
    ----------
    database : str
        The database identifier (name or ID)
    schema : str
        The schema identifier (name or ID)

    Returns:
    -------
    str
        The schema ID in format: {database}.{schema}

    Examples:
    --------
    >>> generate_schema_id("my-project", "sales")
    'my_project.sales'
    """
    return f"{_normalize(database)}.{_normalize(schema)}"


def generate_table_id(database: str, schema: str, table: str) -> str:
    """
    Generate a table ID from database, schema, and table identifiers.

    Parameters
    ----------
    database : str
        The database identifier (name or ID)
    schema : str
        The schema identifier (name or ID)
    table : str
        The table identifier (name or ID)

    Returns:
    -------
    str
        The table ID in format: {database}.{schema}.{table}

    Examples:
    --------
    >>> generate_table_id("my-project", "sales", "orders")
    'my_project.sales.orders'
    """
    return f"{_normalize(database)}.{_normalize(schema)}.{_normalize(table)}"


def generate_column_id(database: str, schema: str, table: str, column: str) -> str:
    """
    Generate a column ID from database, schema, table, and column identifiers.

    Parameters
    ----------
    database : str
        The database identifier (name or ID)
    schema : str
        The schema identifier (name or ID)
    table : str
        The table identifier (name or ID)
    column : str
        The column identifier (name or ID)

    Returns:
    -------
    str
        The column ID in format: {database}.{schema}.{table}.{column}

    Examples:
    --------
    >>> generate_column_id("my-project", "sales", "orders", "order_id")
    'my_project.sales.orders.order_id'
    """
    return f"{_normalize(database)}.{_normalize(schema)}.{_normalize(table)}.{_normalize(column)}"


def generate_value_id(database: str, schema: str, table: str, column: str, value: Any) -> str:
    """
    Generate a value ID from database, schema, table, column, and value.

    Creates a hierarchical ID with a hash suffix based on the value.

    Parameters
    ----------
    database : str
        The database identifier (name or ID)
    schema : str
        The schema identifier (name or ID)
    table : str
        The table identifier (name or ID)
    column : str
        The column identifier (name or ID)
    value : Any
        The value as any type, preferably a string

    Returns:
    -------
    str
        The value ID in format: {database}.{schema}.{table}.{column}.{hashed-value}

    Examples:
    --------
    >>> generate_value_id("my-project", "sales", "orders", "status", "completed")
    'my_project.sales.orders.status.9cdfb439c7876e703e307864c9167a15'
    """
    # Generate a short hash of the value (first 32 characters of MD5)
    value_hash = hashlib.md5(str(value).encode(), usedforsecurity=False).hexdigest()[:32]
    return f"{_normalize(database)}.{_normalize(schema)}.{_normalize(table)}.{_normalize(column)}.{value_hash}"


def generate_glossary_id(glossary: str) -> str:
    """
    Generate a glossary ID.

    Parameters
    ----------
    glossary : str
        The glossary identifier (name or slug)

    Returns:
    -------
    str
        The glossary ID

    Examples:
    --------
    >>> generate_glossary_id("ecommerce_glossary")
    'ecommerce_glossary'
    """
    return _normalize(glossary)


def generate_category_id(glossary: str, category: str) -> str:
    """
    Generate a category ID from glossary and category identifiers.

    Parameters
    ----------
    glossary : str
        The glossary identifier
    category : str
        The category identifier

    Returns:
    -------
    str
        The category ID in format: {glossary}.{category}

    Examples:
    --------
    >>> generate_category_id("ecommerce_glossary", "revenue_metrics")
    'ecommerce_glossary.revenue_metrics'
    """
    return f"{_normalize(glossary)}.{_normalize(category)}"


def generate_business_term_id(glossary: str, category: str, term: str) -> str:
    """
    Generate a business term ID from glossary, category, and term identifiers.

    This produces a dot-separated hierarchical ID (e.g.
    ``ecommerce_glossary.revenue_metrics.gmv``) suitable for the CSV connector.
    It is NOT the same format as the full GCP resource path IDs produced by the
    Dataplex connector (e.g. ``projects/.../glossaries/.../terms/...``). If you
    intend to load glossary data from both the CSV and Dataplex connectors into
    the same graph, supply explicit ``*_id`` values in the CSV that match the
    Dataplex resource paths rather than relying on auto-generation.

    Parameters
    ----------
    glossary : str
        The glossary identifier
    category : str
        The category identifier
    term : str
        The term identifier

    Returns:
    -------
    str
        The business term ID in format: {glossary}.{category}.{term}

    Examples:
    --------
    >>> generate_business_term_id("ecommerce_glossary", "revenue_metrics", "gmv")
    'ecommerce_glossary.revenue_metrics.gmv'
    """
    return f"{_normalize(glossary)}.{_normalize(category)}.{_normalize(term)}"


def create_query_id(query: str) -> str:
    """Create a query ID from a query string."""
    return hashlib.sha256(query.encode()).hexdigest()


def generate_cte_id(query_id: str, cte_name: str) -> str:
    """
    Generate a CTE ID. CTEs are query-scoped, so the id binds the alias to its parent query.

    Examples:
    --------
    >>> generate_cte_id("abc123", "paid")
    'abc123.paid'
    """
    return f"{query_id}.{_normalize(cte_name)}"
