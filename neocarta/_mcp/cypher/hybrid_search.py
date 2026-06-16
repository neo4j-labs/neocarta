"""Hybrid-search-based cypher queries (vector + full text)."""


def get_context_by_table_hybrid_search_cypher() -> str:
    """Get the cypher query to find tables via hybrid vector + full-text search on the Table node.

    Combines a vector search over `table_vector_index` with a full-text search over
    `table_full_text_index`. Scores from each branch are min-max normalized by the branch's
    own maximum score and merged by taking the maximum across branches per table.

    Notes:
    -----
    Expected Cypher parameters:

    queryEmbedding : list[float]
        Embedding for the vector branch.
    queryText : str
        Lucene query for the full-text branch.
    searchTopK : int
        Number of table candidates to fetch from each branch's index.
    maxTables : int
        Maximum number of tables to return in the final result.
    """
    return """
CALL () {
  // vector search tables
  CALL db.index.vector.queryNodes('table_vector_index', $searchTopK, $queryEmbedding)
  YIELD node as table, score as tableScore
  WHERE tableScore > 0.5

  WITH collect({node:table, score:tableScore}) AS nodes, max(tableScore) AS vector_index_max_score
  UNWIND nodes AS n
  RETURN n.node AS node, (n.score / vector_index_max_score) AS score

  UNION

  // full-text search tables
  CALL db.index.fulltext.queryNodes('table_full_text_index', $queryText, {limit: $searchTopK})
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
    table_score: score
} AS result
ORDER BY score DESC
LIMIT $maxTables
    """


def get_context_by_column_hybrid_search_cypher() -> str:
    """Get the cypher query to find tables via hybrid vector + full-text search on the Column node.

    Combines a vector search over `column_vector_index` with a full-text search over
    `column_full_text_index`. Column-level scores are normalized per-branch and merged by max,
    then aggregated up to the parent Table as the per-table average.

    Notes:
    -----
    Expected Cypher parameters:

    queryEmbedding : list[float]
        Embedding for the vector branch.
    queryText : str
        Lucene query for the full-text branch.
    searchTopK : int
        Number of column candidates to fetch from each branch's index.
    maxTables : int
        Maximum number of tables to return in the final result.
    """
    return """
CALL () {
  // vector search columns
  CALL db.index.vector.queryNodes('column_vector_index', $searchTopK, $queryEmbedding)
  YIELD node as col, score as colScore
  WHERE colScore > 0.5

  WITH collect({node:col, score:colScore}) AS nodes, max(colScore) AS vector_index_max_score
  UNWIND nodes AS n
  RETURN n.node AS node, (n.score / vector_index_max_score) AS score

  UNION

  // full-text search columns
  CALL db.index.fulltext.queryNodes('column_full_text_index', $queryText, {limit: $searchTopK})
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


def get_context_by_table_business_term_hybrid_search_cypher() -> str:
    """Get the cypher query to find tables via hybrid vector + business-term-bridged full-text search.

    The full-text branch finds BusinessTerm nodes matching the query, then finds Table nodes
    that (a) also match the query in `table_full_text_index` AND (b) are TAGGED_WITH one of those
    BusinessTerm nodes. For each (table, bt) pair the full-text branch score is
    ``(tableScore/maxTableScore + btScore/maxBtScore) / 2`` — each component min-max normalized
    by its own branch maximum and averaged so the result is in [0,1] and directly comparable
    to the vector branch's normalized score. Combined with a vector search on
    `table_vector_index` via per-branch normalization and max-merge per table.

    Notes:
    -----
    Expected Cypher parameters:

    queryEmbedding : list[float]
        Embedding for the vector branch.
    queryText : str
        Lucene query for both full-text branches (business term + table).
    searchTopK : int
        Number of candidates to fetch from each index call (vector + both full-text).
    maxTables : int
        Maximum number of tables to return in the final result.
    """
    return """
CALL () {
  // vector search tables
  CALL db.index.vector.queryNodes('table_vector_index', $searchTopK, $queryEmbedding)
  YIELD node as table, score as tableScore
  WHERE tableScore > 0.5

  WITH collect({node:table, score:tableScore}) AS nodes, max(tableScore) AS vector_index_max_score
  UNWIND nodes AS n
  RETURN n.node AS node, (n.score / vector_index_max_score) AS score

  UNION

  // full-text search business terms, then bridge to tables tagged with those terms.
  // The FT branch score for each (table, bt) pair is the average of the table
  // full-text score and the business-term full-text score, each min-max normalized
  // by its own branch maximum so the combined score is in [0,1] and directly
  // comparable to the vector branch's normalized score.
  CALL db.index.fulltext.queryNodes('businessterm_full_text_index', $queryText, {limit: $searchTopK})
  YIELD node as bt, score as btScore
  WITH bt, btScore
  CALL db.index.fulltext.queryNodes('table_full_text_index', $queryText, {limit: $searchTopK})
  YIELD node as table, score as tableScore
  WHERE EXISTS {(bt:BusinessTerm)<-[:TAGGED_WITH]-(table:Table)}
  WITH collect({
            node:table,
            tableScore:tableScore,
            businessTerm:bt,
            btScore:btScore}) AS nodes,
        max(tableScore) AS ft_table_max_score,
        max(btScore) AS ft_bt_max_score
  UNWIND nodes AS n
  RETURN n.node AS node,
         ((n.tableScore / ft_table_max_score) + (n.btScore / ft_bt_max_score)) / 2.0 AS score
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
    table_score: score
} AS result
ORDER BY score DESC
LIMIT $maxTables
    """


def get_context_by_column_business_term_hybrid_search_cypher() -> str:
    """Get the cypher query to find tables via hybrid vector + business-term-bridged full-text search on Column.

    The full-text branch finds BusinessTerm nodes matching the query, then finds Column nodes
    that (a) also match the query in `column_full_text_index` AND (b) are TAGGED_WITH one of those
    BusinessTerm nodes. For each (col, bt) pair the full-text branch score is
    ``(colScore/maxColScore + btScore/maxBtScore) / 2`` — each component min-max normalized
    by its own branch maximum and averaged so the result is in [0,1] and directly comparable
    to the vector branch's normalized score. Combined with a vector search on
    `column_vector_index` via per-branch normalization and max-merge per column, then aggregated
    up to the parent Table by average score.

    Notes:
    -----
    Expected Cypher parameters:

    queryEmbedding : list[float]
        Embedding for the vector branch.
    queryText : str
        Lucene query for both full-text branches (business term + column).
    searchTopK : int
        Number of candidates to fetch from each index call (vector + both full-text).
    maxTables : int
        Maximum number of tables to return in the final result.
    """
    return """
CALL () {
  // vector search columns
  CALL db.index.vector.queryNodes('column_vector_index', $searchTopK, $queryEmbedding)
  YIELD node as col, score as colScore
  WHERE colScore > 0.5

  WITH collect({node:col, score:colScore}) AS nodes, max(colScore) AS vector_index_max_score
  UNWIND nodes AS n
  RETURN n.node AS node, (n.score / vector_index_max_score) AS score

  UNION

  // full-text search business terms, then bridge to columns tagged with those terms.
  // The FT branch score for each (col, bt) pair is the average of the column
  // full-text score and the business-term full-text score, each min-max normalized
  // by its own branch maximum so the combined score is in [0,1] and directly
  // comparable to the vector branch's normalized score.
  CALL db.index.fulltext.queryNodes('businessterm_full_text_index', $queryText, {limit: $searchTopK})
  YIELD node as bt, score as btScore
  WITH bt, btScore
  CALL db.index.fulltext.queryNodes('column_full_text_index', $queryText, {limit: $searchTopK})
  YIELD node as col, score as colScore
  WHERE EXISTS {(bt:BusinessTerm)<-[:TAGGED_WITH]-(col:Column)}
  WITH collect({
            node:col,
            colScore:colScore,
            businessTerm:bt,
            btScore:btScore}) AS nodes,
        max(colScore) AS ft_col_max_score,
        max(btScore) AS ft_bt_max_score
  UNWIND nodes AS n
  RETURN n.node AS node,
         ((n.colScore / ft_col_max_score) + (n.btScore / ft_bt_max_score)) / 2.0 AS score
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
