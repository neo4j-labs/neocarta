"""Full-text-search-based cypher queries."""


def get_context_by_table_full_text_search_cypher() -> str:
    """
    Get the cypher query to find tables whose name or description match a full-text query.

    Parameters
    ----------
    queryText: str
        The text to use for the full-text search.
    maxTables: int
        The maximum number of tables to return.

    Returns:
    -------
    str
        The cypher query that returns TableContext rows ordered by full-text score.
    """
    return """
// Full-text search tables
CALL db.index.fulltext.queryNodes('table_full_text_index', $queryText, {limit: $maxTables})
YIELD node as table, score as tableScore

// Get the schema for each table
MATCH (schema:Schema)-[:HAS_TABLE]->(table:Table)

// Find all columns for this table and their references
MATCH (table)-[:HAS_COLUMN]->(col:Column)
OPTIONAL MATCH (col)-[:REFERENCES]-(refCol:Column)<-[:HAS_COLUMN]-(refTable:Table)

// Get example values
OPTIONAL MATCH (col)-[:HAS_VALUE]->(v:Value)

WITH
    schema,
    table,
    col,
    collect(DISTINCT refTable.name + "." + refCol.name) AS refs,
    collect(DISTINCT v.value)[0..5] AS exampleValues,
    tableScore

// Group columns by table and build column objects
WITH
    schema,
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
  }) AS columns,
  tableScore

// Get Database name for Schema
MATCH (schema:Schema)<-[:HAS_SCHEMA]-(db:Database)

RETURN {
    table_name: table.name,
    table_description: table.description,
    database_name: db.name,
    schema_name: schema.name,
    columns: columns,
    num_columns: size(columns),
    table_score: tableScore
} AS result
ORDER BY tableScore DESC
LIMIT $maxTables
"""


def get_context_by_column_full_text_search_cypher() -> str:
    """
    Get the cypher query to find tables whose columns match a full-text query.

    Parameters
    ----------
    queryText: str
        The text to use for the full-text search.
    maxTables: int
        The maximum number of tables to return.

    Returns:
    -------
    str
        The cypher query that returns TableContext rows aggregated from matching columns,
        ordered by average column full-text score.
    """
    return """
// Full-text search columns
CALL db.index.fulltext.queryNodes('column_full_text_index', $queryText, {limit: $maxTables})
YIELD node as col, score

// Get the table for each matching column
MATCH (col)<-[:HAS_COLUMN]-(table:Table)

// Find all references for this column (both directions)
OPTIONAL MATCH (col)-[:REFERENCES]-(refCol:Column)<-[:HAS_COLUMN]-(refTable:Table)

// Get example values
OPTIONAL MATCH (col)-[:HAS_VALUE]->(v:Value)

WITH
    table,
    col,
    score,
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
  }) AS columns,
  AVG(score) AS columnAvgScore

// Get Schema and Database names for Tables
MATCH (table)<-[:HAS_TABLE]-(schema:Schema)<-[:HAS_SCHEMA]-(db:Database)

RETURN {
    table_name: table.name,
    table_description: table.description,
    database_name: db.name,
    schema_name: schema.name,
    columns: columns,
    num_columns: size(columns),
    column_avg_score: columnAvgScore
} AS result
ORDER BY columnAvgScore DESC
LIMIT $maxTables
"""
