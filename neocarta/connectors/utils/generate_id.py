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


def generate_governance_tag_key_id(source: str, key: str) -> str:
    """
    Generate a GovernanceTagKey id, namespaced by source.

    Tag keys collide across vendors and accounts (a Databricks ``environment`` tag
    is unrelated to a Snowflake ``environment`` tag), so the id is scoped by a
    source identifier — typically the metastore / account id, like the Glossary
    id is scoped by its metastore.

    Parameters
    ----------
    source : str
        The source namespace (e.g. metastore or account id).
    key : str
        The governance tag key.

    Returns:
    -------
    str
        The governance tag key id in format: {source}.{key}

    Examples:
    --------
    >>> generate_governance_tag_key_id("aws:us-west-2:abc-123", "sensitivity")
    'aws:us_west_2:abc_123.sensitivity'
    """
    return f"{_normalize(source)}.{_normalize(key)}"


def generate_governance_tag_value_id(source: str, key: str, value: str) -> str:
    """
    Generate a GovernanceTagValue id, namespaced by source and key.

    The value segment is content-hashed (md5, like :func:`generate_value_id`) rather
    than normalized, because governance-tag values are case- and separator-sensitive:
    normalizing would collapse distinct values such as ``High Risk`` / ``high-risk`` /
    ``high_risk`` into one id. The original value is preserved on the node's ``name``;
    only the id is hashed. (Keys are still normalized and may collapse — by design.)

    Parameters
    ----------
    source : str
        The source namespace (e.g. metastore or account id).
    key : str
        The governance tag key.
    value : str
        The allowed value.

    Returns:
    -------
    str
        The governance tag value id in format: {source}.{key}.{hashed-value}

    Examples:
    --------
    >>> generate_governance_tag_value_id("aws:us-west-2:abc-123", "sensitivity", "pii")
    'aws:us_west_2:abc_123.sensitivity.1eae74adfc325f04a8506be8bd11c67a'
    """
    value_hash = hashlib.md5(str(value).encode(), usedforsecurity=False).hexdigest()[:32]
    return f"{_normalize(source)}.{_normalize(key)}.{value_hash}"


def generate_governance_tag_instance_id(source_id: str, key: str, value: str) -> str:
    """
    Generate a GovernanceTag (assignment) id.

    Governance tags are modelled per assignment — one node per tagged object — so
    the id is scoped by the tagged object's id, making each assignment a distinct
    node even when many objects share the same (key, value).

    Parameters
    ----------
    source_id : str
        The id of the tagged object (column / table / schema id). This MUST
        already be a ``generate_*_id`` output — it is intentionally **not**
        re-normalized here (it is already normalized and may legitimately contain
        dotted segments), unlike the ``source`` segment of
        :func:`generate_governance_tag_key_id` / :func:`generate_governance_tag_value_id`.
    key : str
        The applied tag key.
    value : str
        The applied tag value.

    Returns:
    -------
    str
        The governance tag assignment id in format: {source_id}.{key}.{hashed-value}

    Examples:
    --------
    >>> generate_governance_tag_instance_id("proj.sales.orders.email", "sensitivity", "pii")
    'proj.sales.orders.email.sensitivity.1eae74adfc325f04a8506be8bd11c67a'
    """
    # Value is content-hashed (see generate_governance_tag_value_id) so case/separator-
    # distinct values don't collapse; the source_id is a pre-built, already-normalized id.
    value_hash = hashlib.md5(str(value).encode(), usedforsecurity=False).hexdigest()[:32]
    return f"{source_id}.{_normalize(key)}.{value_hash}"


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


def generate_osi_semantic_model_id(name: str) -> str:
    """
    Generate an OSI semantic model ID from its name.

    Examples:
    --------
    >>> generate_osi_semantic_model_id("Sales Model")
    'sales_model'
    """
    return _normalize(name)


def generate_metric_id(semantic_model: str, metric: str) -> str:
    """
    Generate a Metric ID from its parent semantic model and metric name.

    Examples:
    --------
    >>> generate_metric_id("sales_model", "gross_revenue")
    'sales_model.gross_revenue'
    """
    return f"{_normalize(semantic_model)}.{_normalize(metric)}"


def generate_join_id(semantic_model: str, join: str) -> str:
    """
    Generate a Join ID from its parent semantic model and join name.

    Examples:
    --------
    >>> generate_join_id("sales_model", "orders_to_customers")
    'sales_model.orders_to_customers'
    """
    return f"{_normalize(semantic_model)}.{_normalize(join)}"


def generate_expression_id(owner_id: str, dialect: str, expression: str) -> str:
    """
    Generate an Expression ID, content-addressed by (dialect, expression) under
    the owning column/metric.

    Identical expressions on the same owner collapse to one node.

    Examples:
    --------
    >>> generate_expression_id("sales_model.gross_revenue", "ANSI_SQL", "SUM(amount)")
    'sales_model.gross_revenue.55cfe9b30c52a6f9d6c9c91e7af83c40'
    """
    digest = hashlib.md5(f"{dialect}::{expression}".encode(), usedforsecurity=False).hexdigest()[
        :32
    ]
    return f"{owner_id}.{digest}"


def generate_ai_context_id(semantic_model: str, data: str) -> str:
    """
    Generate an OsiAiContext aspect ID, content-addressed within a semantic model.

    Identical AI-context payloads under the same semantic model produce one
    aspect node referenced by every entity that shares the content.

    Examples:
    --------
    >>> generate_ai_context_id("sales_model", '{"synonyms": ["customer"]}')
    'sales_model.b1d29bb39c6cea25e64fa5d8e2c2c4b3'
    """
    digest = hashlib.md5(data.encode(), usedforsecurity=False).hexdigest()[:32]
    return f"{_normalize(semantic_model)}.{digest}"


def generate_query_column_id(query_id: str, column: str) -> str:
    """
    Generate a Column ID for a column owned by a Query (rather than a Table).

    Used when an OSI dataset's source is a SQL query: the dataset's fields become
    columns of the underlying Query node and need an id rooted on the query id
    (which is itself a SHA-256 hash, not a dotted identifier).

    Examples:
    --------
    >>> generate_query_column_id("a1b2c3", "order_id")
    'a1b2c3.order_id'
    """
    return f"{query_id}.{_normalize(column)}"


def generate_custom_extension_id(semantic_model: str, vendor: str, data: str) -> str:
    """
    Generate an OsiCustomExtensions aspect ID, content-addressed by (vendor, data)
    under the semantic model.

    Examples:
    --------
    >>> generate_custom_extension_id("sales_model", "SNOWFLAKE", '{"warehouse": "S"}')
    'sales_model.<hash>'  # doctest: +SKIP
    """
    digest = hashlib.md5(f"{vendor}::{data}".encode(), usedforsecurity=False).hexdigest()[:32]
    return f"{_normalize(semantic_model)}.{digest}"
