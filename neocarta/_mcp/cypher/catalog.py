"""Catalog and listing cypher queries (schemas, tables, indexes, full schema dump)."""


def list_indexes_cypher() -> str:
    """Get the cypher query to list all indexes."""
    return """
SHOW INDEXES
YIELD name, state, populationPercent, type, entityType, labelsOrTypes, properties, indexProvider, owningConstraint
    """


def list_vector_indexes_cypher() -> str:
    """Get the cypher query to list all vector indexes."""
    return f"""
{list_indexes_cypher()}
WHERE type = 'VECTOR'
RETURN *
    """


def list_full_text_indexes_cypher() -> str:
    """Get the cypher query to list all full text indexes."""
    return f"""
{list_indexes_cypher()}
WHERE type = 'FULLTEXT'
RETURN *
    """


def list_search_indexes_cypher() -> str:
    """
    Get the cypher query that returns one row per (node label, search index type) pair
    for VECTOR and FULLTEXT node indexes. Used to gate MCP tool registration on the
    indexes that are actually present in the database.

    Returns:
    -------
    str
        Each row has ``label`` (str) and ``type`` (``'VECTOR' | 'FULLTEXT'``). A full-text
        index spanning multiple labels yields one row per label.
    """
    return f"""
{list_indexes_cypher()}
WHERE type IN ['VECTOR', 'FULLTEXT']
RETURN *
    """


def list_schemas_cypher() -> str:
    """
    Get the cypher query to list all schemas and their databases.

    Returns:
    -------
    str
        The cypher query to list all schemas and their databases.
    """
    return """
MATCH (d:Database)-[:HAS_SCHEMA]->(schema:Schema)
RETURN d.name as database_name, schema.name as schema_name
    """


def list_tables_by_schema_cypher() -> str:
    """
    Get the cypher query to list all tables for a given schema.

    Parameters
    ----------
    schema_name: str
        The name of the schema to list tables for.

    Returns:
    -------
    str
        The cypher query to list all tables for a given schema.
    """
    return """
MATCH (s:Schema {name: $schemaName})-[:HAS_TABLE]->(t:Table)
RETURN s.name as schema_name, collect(t.name) as table_names
    """


def get_full_metadata_schema_cypher() -> str:
    """
    Get the cypher query to get the full metadata schema for the database.

    Returns:
    -------
    str
        The cypher query to get the full metadata schema for the database.
    """
    return """
// Get the columns for each table
MATCH (col:Column)<-[:HAS_COLUMN]-(table:Table)

// Find all references for this column (both directions)
OPTIONAL MATCH (col)-[:REFERENCES]-(refCol:Column)<-[:HAS_COLUMN]-(refTable:Table)

// Get example values
OPTIONAL MATCH (col)-[:HAS_VALUE]->(v:Value)

WITH
    table,
    col,
    collect(DISTINCT refTable.name + "." + refCol.name) AS refs,
    collect(DISTINCT v.value)[0..5] AS exampleValues

// Group columns by table and build column objects
WITH
    table,
    collect({
        column_name: col.name,
        column_description: col.description,
        data_type: col.type,
        examples: exampleValues,
        key_type: CASE
            WHEN col.is_primary_key THEN "primary"
            WHEN col.is_foreign_key THEN "foreign"
            ELSE null
        END,
        nullable: col.nullable,
        references: refs
    }) AS columns

// Get Schema and Database names for Tables
MATCH (table)<-[:HAS_TABLE]-(schema:Schema)<-[:HAS_SCHEMA]-(db:Database)

WITH
    table,
    columns,
    schema.name as schema_name,
    db.name as database_name

RETURN {
    table_name: table.name,
    table_description: table.description,
    database_name: database_name,
    schema_name: schema_name,
    columns: columns
} AS result
ORDER BY table.name
"""
