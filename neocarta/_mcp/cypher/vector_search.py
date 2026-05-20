"""Vector-search-based cypher queries."""


def get_context_by_column_vector_search_cypher() -> str:
    """Get the cypher query to find metadata by column semantic similarity to the query.

    Notes:
    -----
    Expected Cypher parameters:

    queryEmbedding : list[float]
        Embedding to compare against ``column_vector_index``.
    searchTopK : int
        Number of column candidates to fetch from the vector index.
    maxTables : int
        Maximum number of tables to return in the final result.

    Uses the ``column_vector_index`` index (library convention).
    """
    return """
// Find similar columns by embedding
CALL db.index.vector.queryNodes('column_vector_index', $searchTopK, $queryEmbedding)
YIELD node as col, score
WHERE score > 0.5

// Get the columns for each table
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


def get_context_by_table_vector_search_cypher() -> str:
    """Get the cypher query to find metadata by table semantic similarity to the query.

    Notes:
    -----
    Expected Cypher parameters:

    queryEmbedding : list[float]
        Embedding to compare against ``table_vector_index``.
    searchTopK : int
        Number of table candidates to fetch from the vector index.
    maxTables : int
        Maximum number of tables to return in the final result.

    Uses the ``table_vector_index`` index (library convention).
    """
    return """
// Find similar tables by embedding
CALL db.index.vector.queryNodes('table_vector_index', $searchTopK, $queryEmbedding)
YIELD node as table, score as tableScore
WHERE tableScore > 0.5

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


def get_context_by_schema_and_table_vector_search_cypher() -> str:
    """Get the cypher query to find metadata by schema and table semantic similarity to the query.

    Notes:
    -----
    Expected Cypher parameters:

    queryEmbedding : list[float]
        Embedding to compare against ``schema_vector_index`` and to score tables in-line.
    searchTopK : int
        Number of schema candidates to fetch from the vector index.
    maxTables : int
        Maximum number of tables to return in the final result.

    Uses the ``schema_vector_index`` index (library convention). Table similarity is
    computed in-line via ``vector.similarity.cosine``
    """
    return """
// Find similar schemas by embedding
CALL db.index.vector.queryNodes('schema_vector_index', $searchTopK, $queryEmbedding)
YIELD node as schema, score as schemaScore
WHERE schemaScore > 0.5

// Get the tables for each schema
// Only get tables that are nearly as similar as the schema
MATCH (schema:Schema)-[:HAS_TABLE]->(table:Table)

WITH
    schema,
    schemaScore,
    table,
    vector.similarity.cosine(table.embedding, $queryEmbedding) as tableScore
WHERE tableScore > schemaScore - 0.2

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
    schemaScore,
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
  schemaScore,
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
    table_score: tableScore,
    schema_score: schemaScore
} AS result
ORDER BY schemaScore DESC, tableScore DESC
LIMIT $maxTables
"""
