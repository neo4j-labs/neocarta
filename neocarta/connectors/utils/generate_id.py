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
