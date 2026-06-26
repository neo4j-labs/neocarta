"""Full-text-search-based cypher queries."""


def get_context_by_table_full_text_search_cypher() -> str:
    """Get the cypher query to find tables whose name or description match a full-text query.

    Notes:
    -----
    Expected Cypher parameters:

    queryText : str
        Lucene query for ``table_full_text_index``.
    searchTopK : int
        Number of table candidates to fetch from the full-text index.
    maxTables : int
        Maximum number of tables to return in the final result.

    Uses the ``table_full_text_index`` index (library convention).
    """
    return """
// Full-text search tables
CALL db.index.fulltext.queryNodes('table_full_text_index', $queryText, {limit: $searchTopK})
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
        label: col.label,
        is_time_dimension: col.is_time_dimension,
        examples: exampleValues,
        key_type: CASE
            WHEN col.is_primary_key THEN "primary"
            WHEN col.is_foreign_key THEN "foreign"
            ELSE null
        END,
        nullable: col.nullable,
        references: refs,
        expressions: COLLECT {
            MATCH (col)-[:HAS_EXPRESSION]->(e:Expression)
            RETURN {dialect: e.dialect, expression: e.expression}
        },
        aspects: COLLECT {
            MATCH (col)-[:HAS_ASPECT]->(a:Aspect)
            RETURN {
                aspect_type: CASE
                    WHEN a:OsiAiContext THEN "ai_context"
                    WHEN a:OsiCustomExtensions THEN "custom_extensions"
                    ELSE "unknown"
                END,
                data: a.data,
                vendor_name: a.vendor_name
            }
        }
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
    primary_key: coalesce(table.primary_key, []),
    aspects: COLLECT {
        MATCH (table)-[:HAS_ASPECT]->(a:Aspect)
        RETURN {
            aspect_type: CASE
                WHEN a:OsiAiContext THEN "ai_context"
                WHEN a:OsiCustomExtensions THEN "custom_extensions"
                ELSE "unknown"
            END,
            data: a.data,
            vendor_name: a.vendor_name
        }
    },
    table_score: tableScore
} AS result
ORDER BY tableScore DESC
LIMIT $maxTables
"""


def get_context_by_column_full_text_search_cypher() -> str:
    """Get the cypher query to find tables whose columns match a full-text query.

    Notes:
    -----
    Expected Cypher parameters:

    queryText : str
        Lucene query for ``column_full_text_index``.
    searchTopK : int
        Number of column candidates to fetch from the full-text index.
    maxTables : int
        Maximum number of tables to return in the final result.

    Uses the ``column_full_text_index`` index (library convention).
    """
    return """
// Full-text search columns
CALL db.index.fulltext.queryNodes('column_full_text_index', $queryText, {limit: $searchTopK})
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
        label: col.label,
        is_time_dimension: col.is_time_dimension,
        examples: exampleValues,
        key_type: CASE
            WHEN col.is_primary_key THEN "primary"
            WHEN col.is_foreign_key THEN "foreign"
        ELSE null
        END,
        nullable: col.nullable,
        references: refs,
        expressions: COLLECT {
            MATCH (col)-[:HAS_EXPRESSION]->(e:Expression)
            RETURN {dialect: e.dialect, expression: e.expression}
        },
        aspects: COLLECT {
            MATCH (col)-[:HAS_ASPECT]->(a:Aspect)
            RETURN {
                aspect_type: CASE
                    WHEN a:OsiAiContext THEN "ai_context"
                    WHEN a:OsiCustomExtensions THEN "custom_extensions"
                    ELSE "unknown"
                END,
                data: a.data,
                vendor_name: a.vendor_name
            }
        }
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
    primary_key: coalesce(table.primary_key, []),
    aspects: COLLECT {
        MATCH (table)-[:HAS_ASPECT]->(a:Aspect)
        RETURN {
            aspect_type: CASE
                WHEN a:OsiAiContext THEN "ai_context"
                WHEN a:OsiCustomExtensions THEN "custom_extensions"
                ELSE "unknown"
            END,
            data: a.data,
            vendor_name: a.vendor_name
        }
    },
    column_avg_score: columnAvgScore
} AS result
ORDER BY columnAvgScore DESC
LIMIT $maxTables
"""
