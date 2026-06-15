# RDBMS Graph Data Model Components

This module contains the graph data model components in an RDBMS metadata graph.

**The data model components defined in this document are subject to change throughout development.**

## Core Data Model

The core data model consists of four nodes and four relationships. 

Nodes
* [`Database`](./core.py#L7)
    * Top level node containing information about the database
* [`Schema`](./core.py#L42)
    * Contains details about the database schema
* [`Table`](./core.py#L66)
    * Contains information about a table within the database schema
* [`Column`](./core.py#L90)
    * Contains information about a column within a table

Relationships
* [`(:Database)-[:HAS_SCHEMA]->(:Schema)`](./core.py#L121)
    * Defines the database to schema hierarchy
* [`(:Schema)-[:HAS_TABLE]->(:Table)`](./core.py#L131)
    * Defines the schema to table hierarchy
* [`(:Table)-[:HAS_COLUMN]->(:Column)`](./core.py#L141)
    * Defines the table to column hierarchy
* [`(:Column)-[:REFERENCES]->(:Column)`](./core.py#L151)
    * Defines relationship where two columns represent the same information, but exist in different tables
    * Columns identifed with this relationship may be used to join their respective tables
    * Carries an optional `criteria` property holding the join condition between the two columns

## Value Nodes

Value nodes provide example values and enums that may augment the database context. 
For example upon matching a `Column`, `k` values may be returned as examples by traversing to related `Value` nodes.
If values are constrained to a set of options, these may be provded as an enum in the context to provide additional guidance.

Nodes
* [`Value`](./expanded.py#L11)
    * Represents a single unique value within a column
    * Values are unique on the column level within the graph
    * A value may not have more than one relationship with a `Column` node

Relationships
* [`(:Column)-[:HAS_VALUE]->(:Value)`](./expanded.py#L26)
    * Defines a value's parent column

## Queries

Queries may be cached in the graph and provided as few-shot examples in the context.
They may also be used to shortcut query generation, if they fully address the current task.
Query parsing (e.g. from query logs) may also surface inline Common Table Expressions, which are
stored as query-scoped `CTE` nodes so they can be distinguished from real catalog tables.

Nodes
* [`Query`](./expanded.py#L113)
    * A SQL query, optionally with a logical `name` (e.g. the OSI dataset name when sourced from OSI)
* [`CTE`](./expanded.py#L148)
    * A Common Table Expression defined inline by a query — a query-scoped, virtual table

Relationships
* [`(:Query)-[:USES_TABLE]->(:Table)`](./expanded.py#L128)
* [`(:Query)-[:USES_COLUMN]->(:Column)`](./expanded.py#L138)
* [`(:Query)-[:DEFINES]->(:CTE)`](./expanded.py#L163)
    * Links a query to the CTEs it defines

## Glossary Data Model

Data catalogs allow business terms to be defined and linked to tables and columns.
This allows relationships to be inferred by shared business terms across assets.
For example `TableA.customer_id` and `TableB.cstmr_id` both tagged with the business term "Customer ID" implies those columns can be used to join their respective tables.

Nodes
* [`Glossary`](./expanded.py#L36)
    * The glossary containing categories and business terms
    * Carries an optional `resource_path` (e.g. the Dataplex resource name)
* [`Category`](./expanded.py#L48)
    * Contains information about a category in the glossary
    * Carries an optional `resource_path` (e.g. the Dataplex resource name)
* [`BusinessTerm`](./expanded.py#L60)
    * A leaf level term in the glossary
    * Defines a globally recognized term across databases in the system
    * Carries an optional `resource_path` (e.g. the Dataplex resource name)

Relationships
* [`(:Glossary)-[:HAS_CATEGORY]->(:Category)`](./expanded.py#L93)
    * Defines glossary to category hierarchy
* [`(:Category)-[:HAS_BUSINESS_TERM]->(:BusinessTerm)`](./expanded.py#L103)
    * Defines category to business term hierarchy
* [`(:Column|:Table|:Schema|:Metric)-[:TAGGED_WITH]->(:BusinessTerm)`](./expanded.py#L77)
    * Defines that an entity (column, table, schema, or metric) is tagged with a business term
    * Columns tagged with the same business term may be used to join their respective tables

## OSI Semantic Model

The [Open Semantic Interchange (OSI)](https://github.com/open-semantic-interchange/OSI) connector
extends the core model with semantic-model nodes. These reuse the core `Database` / `Schema` and
add OSI subtypes that carry extra metadata. See the [OSI connector README](../../connectors/osi/README.md)
for the full data model diagram and behavioral notes.

Nodes
* [`Domain`](./expanded.py#L173) / [`OsiSemanticModel`](./expanded.py#L184)
    * A semantic grouping of data assets; `OsiSemanticModel` is a `Domain` subtype representing a full OSI spec instance, stored as a `(:Domain&OsiSemanticModel)` node
* [`OsiTable`](./expanded.py#L196)
    * A `Table` subtype with OSI key metadata (`source`, `primary_key`, `unique_keys`), stored as `(:Table&OsiTable)`
* [`OsiColumn`](./expanded.py#L223)
    * A `Column` subtype with OSI display metadata (`label`, `is_time_dimension`), stored as `(:Column&OsiColumn)`
* [`Metric`](./expanded.py#L241)
    * A measurable quantity in an OSI semantic model
* [`Join`](./expanded.py#L293)
    * A join definition between two tables (`from_columns` / `to_columns` preserve composite-key ordering)
* [`Expression`](./expanded.py#L283)
    * A dialect-specific computation expression
* [`Aspect`](./expanded.py#L252) / [`OsiAiContext`](./expanded.py#L261) / [`OsiCustomExtensions`](./expanded.py#L274)
    * Additional context attached to entities; `OsiAiContext` carries agent-facing context and `OsiCustomExtensions` carries vendor-specific metadata, both as JSON-encoded strings

Relationships
* [`(:Domain)-[:HAS_TABLE]->(:Table)`](./expanded.py#L369)
    * A semantic model owns its datasets (tables) directly
* [`(:Domain)-[:HAS_QUERY]->(:Query)`](./expanded.py#L385)
    * OSI datasets whose `source` is a SQL query are stored as `Query` nodes
* [`(:Domain)-[:HAS_METRIC]->(:Metric)`](./expanded.py#L359)
* [`(:Join)-[:HAS_SOURCE_TABLE]->(:Table)`](./expanded.py#L399) / [`(:Join)-[:HAS_TARGET_TABLE]->(:Table)`](./expanded.py#L409)
* [`(:Column)-[:USED_IN_JOIN]->(:Join)`](./expanded.py#L335)
* [`(:Column|:Metric)-[:HAS_EXPRESSION]->(:Expression)`](./expanded.py#L345)
* [`(:Schema|:Table|:Column|:Query|:Metric|:Join|:Domain)-[:HAS_ASPECT]->(:Aspect)`](./expanded.py#L316)

## Data Stewards **(Not Implemented)**

Data catalogs allows data stewards to be defined and linked to the appropriate assets in the database.

Nodes
* `Steward`

Relationships
* `(:Steward)-[:STEWARDS_SCHEMA]->(:Schema)`
* `(:Steward)-[:STEWARDS_TABLE]->(:Table)`
* `(:Steward)-[:STEWARDS_CATEGORY]->(:Category)`
* `(:Steward)-[:STEWARDS_BUSINESS_TERM]->(:BusinessTerm)`

## Rules **(Not Implemented)**

Data catalogs allow for data quality and business rules to be defined and linked to the appropriate assets. 
These rules may be returned alongside their respective data assets to guide the agent in how to use them properly.

Nodes
* `DataQualityRule`
    * A rule that enforces data correctness and completeness
* `BusinessRule`
    * A rule that describes business logic and constraints

Relationships
* `(:DataQualityRule)-[:ENFORCES_TABLE]->(:Table)`
* `(:DataQualityRule)-[:ENFORCES_COLUMN]->(:Column)`
* `(:BusinessRule)-[:APPLIES_TO_TABLE]->(:Table)`
* `(:BusinessRule)-[:APPLIES_TO_COLUMN]->(:Column)`
* `(:BusinessRule)-[:RELATED_TO]->(:BusinessTerm)`
    * Defines which business terms are related to the business rule
    * This relationship may be used to identify columns that are impacted by a business rule 

## Transformations **(Not Implemented)**

`Transform` nodes trace data lineage and how downstream columns are calculated. 
These nodes may also contain metadata such as SQL queries, transformation logic or algorithms run to process the data.

Nodes
* `Transform`

Relationships
* `(:Column)-[:INPUT_TO]->(:Transform)`
`(:Transform)-[:PRODUCES]->(:Column)`



