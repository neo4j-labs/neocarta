"""Hybrid-search-based cypher queries (vector + full text)."""


def get_context_by_table_hybrid_search_cypher() -> str:
    """
    Get the cypher query to find tables via hybrid vector + full-text search on the Table node.

    Combines a vector search over `table_vector_index` with a full-text search over
    `table_full_text_index`. Scores from each branch are min-max normalized by the branch's
    own maximum score and merged by taking the maximum across branches per table.

    Parameters
    ----------
    queryEmbedding: list[float]
        The embedding to use for the vector branch.
    queryText: str
        The text to use for the full-text branch.
    maxTables: int
        The maximum number of tables to return.
    """
    return """
CALL () {
  // vector search tables
  CALL db.index.vector.queryNodes('table_vector_index', $maxTables, $queryEmbedding)
  YIELD node as table, score as tableScore
  WHERE tableScore > 0.5

  WITH collect({node:table, score:tableScore}) AS nodes, max(tableScore) AS vector_index_max_score
  UNWIND nodes AS n
  RETURN n.node AS node, (n.score / vector_index_max_score) AS score

  UNION

  // full-text search tables
  CALL db.index.fulltext.queryNodes('table_full_text_index', $queryText, {limit: $maxTables})
  YIELD node as table, score as tableScore

  WITH collect({node:table, score:tableScore}) AS nodes, max(tableScore) AS ft_index_max_score
  UNWIND nodes AS n
  RETURN n.node AS node, (n.score / ft_index_max_score) AS score
}
WITH node as table, max(score) AS score
ORDER BY score DESC
LIMIT $maxTables

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
    score

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
  score

// Get Database name for Schema
MATCH (schema:Schema)<-[:HAS_SCHEMA]-(db:Database)

RETURN {
    table_name: table.name,
    table_description: table.description,
    database_name: db.name,
    schema_name: schema.name,
    columns: columns,
    num_columns: size(columns),
    table_score: score
} AS result
ORDER BY score DESC
LIMIT $maxTables
    """


def get_context_by_column_hybrid_search_cypher() -> str:
    """
    Get the cypher query to find tables via hybrid vector + full-text search on the Column node.

    Combines a vector search over `column_vector_index` with a full-text search over
    `column_full_text_index`. Column-level scores are normalized per-branch and merged by max,
    then aggregated up to the parent Table as the per-table average.

    Parameters
    ----------
    queryEmbedding: list[float]
        The embedding to use for the vector branch.
    queryText: str
        The text to use for the full-text branch.
    maxTables: int
        The maximum number of tables to return.
    """
    return """
CALL () {
  // vector search columns
  CALL db.index.vector.queryNodes('column_vector_index', $maxTables, $queryEmbedding)
  YIELD node as col, score as colScore
  WHERE colScore > 0.5

  WITH collect({node:col, score:colScore}) AS nodes, max(colScore) AS vector_index_max_score
  UNWIND nodes AS n
  RETURN n.node AS node, (n.score / vector_index_max_score) AS score

  UNION

  // full-text search columns
  CALL db.index.fulltext.queryNodes('column_full_text_index', $queryText, {limit: $maxTables})
  YIELD node as col, score as colScore

  WITH collect({node:col, score:colScore}) AS nodes, max(colScore) AS ft_index_max_score
  UNWIND nodes AS n
  RETURN n.node AS node, (n.score / ft_index_max_score) AS score
}
WITH node as col, max(score) AS score

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


def get_context_by_table_business_term_hybrid_search_cypher() -> str:
    """
    Get the cypher query to find tables via hybrid vector + business-term-bridged full-text search.

    The full-text branch finds BusinessTerm nodes matching the query, then finds Table nodes
    that (a) also match the query in `table_full_text_index` AND (b) are TAGGED_WITH one of those
    BusinessTerm nodes. Combined with a vector search on `table_vector_index` via min-max
    normalization and max-merge per table.

    Parameters
    ----------
    queryEmbedding: list[float]
        The embedding to use for the vector branch.
    queryText: str
        The text to use for the full-text branches (business term + table).
    maxTables: int
        The maximum number of tables to return.
    """
    return """
CALL () {
  // vector search tables
  CALL db.index.vector.queryNodes('table_vector_index', $maxTables, $queryEmbedding)
  YIELD node as table, score as tableScore
  WHERE tableScore > 0.5

  WITH collect({node:table, score:tableScore}) AS nodes, max(tableScore) AS vector_index_max_score
  UNWIND nodes AS n
  RETURN n.node AS node, (n.score / vector_index_max_score) AS score

  UNION

  // full-text search business terms, then bridge to tables tagged with those terms
  CALL db.index.fulltext.queryNodes('businessterm_full_text_index', $queryText, {limit: $maxTables})
  YIELD node as bt, score as btScore
  WITH bt, btScore
  CALL db.index.fulltext.queryNodes('table_full_text_index', $queryText, {limit: $maxTables})
  YIELD node as table, score as tableScore
  WHERE EXISTS {(bt:BusinessTerm)<-[:TAGGED_WITH]-(table:Table)}
  WITH collect({
            node:table,
            score:tableScore,
            businessTerm:bt,
            btScore:btScore}) AS nodes,
        max(tableScore) AS ft_index_max_score
  UNWIND nodes AS n
  RETURN n.node AS node, (n.score / ft_index_max_score) AS score
}
WITH node as table, max(score) AS score
ORDER BY score DESC
LIMIT $maxTables

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
    score

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
  score

// Get Database name for Schema
MATCH (schema:Schema)<-[:HAS_SCHEMA]-(db:Database)

RETURN {
    table_name: table.name,
    table_description: table.description,
    database_name: db.name,
    schema_name: schema.name,
    columns: columns,
    num_columns: size(columns),
    table_score: score
} AS result
ORDER BY score DESC
LIMIT $maxTables
    """


def get_context_by_column_business_term_hybrid_search_cypher() -> str:
    """
    Get the cypher query to find tables via hybrid vector + business-term-bridged full-text search on Column.

    The full-text branch finds BusinessTerm nodes matching the query, then finds Column nodes
    that (a) also match the query in `column_full_text_index` AND (b) are TAGGED_WITH one of those
    BusinessTerm nodes. Combined with a vector search on `column_vector_index` via min-max
    normalization and max-merge per column, then aggregated up to the parent Table.

    Parameters
    ----------
    queryEmbedding: list[float]
        The embedding to use for the vector branch.
    queryText: str
        The text to use for the full-text branches (business term + column).
    maxTables: int
        The maximum number of tables to return.
    """
    return """
CALL () {
  // vector search columns
  CALL db.index.vector.queryNodes('column_vector_index', $maxTables, $queryEmbedding)
  YIELD node as col, score as colScore
  WHERE colScore > 0.5

  WITH collect({node:col, score:colScore}) AS nodes, max(colScore) AS vector_index_max_score
  UNWIND nodes AS n
  RETURN n.node AS node, (n.score / vector_index_max_score) AS score

  UNION

  // full-text search business terms, then bridge to columns tagged with those terms
  CALL db.index.fulltext.queryNodes('businessterm_full_text_index', $queryText, {limit: $maxTables})
  YIELD node as bt, score as btScore
  WITH bt, btScore
  CALL db.index.fulltext.queryNodes('column_full_text_index', $queryText, {limit: $maxTables})
  YIELD node as col, score as colScore
  WHERE EXISTS {(bt:BusinessTerm)<-[:TAGGED_WITH]-(col:Column)}
  WITH collect({
            node:col,
            score:colScore,
            businessTerm:bt,
            btScore:btScore}) AS nodes,
        max(colScore) AS ft_index_max_score
  UNWIND nodes AS n
  RETURN n.node AS node, (n.score / ft_index_max_score) AS score
}
WITH node as col, max(score) AS score

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
