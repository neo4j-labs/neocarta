# Query Data Model

Queries may be cached in the graph and provided as few-shot examples in the
context. They may also be used to shortcut query generation if they fully
address the current task. Query parsing (e.g. from query logs) may also surface
inline Common Table Expressions, which are stored as query-scoped `CTE` nodes so
they can be distinguished from real catalog tables.

Nodes
* [`Query`](./models.py#L6)
    * A SQL query, optionally with a logical `name` (e.g. the OSI dataset name
      when sourced from OSI)
* [`CTE`](./models.py#L21)
    * A Common Table Expression defined inline by a query — a query-scoped,
      virtual table

Relationships
* [`(:Query)-[:USES_TABLE]->(:Table)`](./models.py#L36)
* [`(:Query)-[:USES_COLUMN]->(:Column)`](./models.py#L46)
* [`(:Query)-[:DEFINES]->(:CTE)`](./models.py#L56)
    * Links a query to the CTEs it defines
