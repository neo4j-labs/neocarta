# RDBMS Structural Data Model

The structural components of an RDBMS metadata graph.

**The data model components defined in this document are subject to change throughout development.**

## Core Data Model

The core data model consists of four nodes and four relationships.

Nodes
* [`Database`](./models.py#L8)
    * Top level node containing information about the database
* [`Schema`](./models.py#L30)
    * Contains details about the database schema
* [`Table`](./models.py#L43)
    * Contains information about a table within the database schema
* [`Column`](./models.py#L56)
    * Contains information about a column within a table

Relationships
* [`(:Database)-[:HAS_SCHEMA]->(:Schema)`](./models.py#L76)
    * Defines the database to schema hierarchy
* [`(:Schema)-[:HAS_TABLE]->(:Table)`](./models.py#L86)
    * Defines the schema to table hierarchy
* [`(:Table)-[:HAS_COLUMN]->(:Column)`](./models.py#L96)
    * Defines the table to column hierarchy
* [`(:Column)-[:REFERENCES]->(:Column)`](./models.py#L106)
    * Defines a relationship where two columns represent the same information but
      exist in different tables
    * Columns identified with this relationship may be used to join their
      respective tables
    * Carries an optional `criteria` property holding the join condition between
      the two columns

## Related layers

The following concerns build on this structural core and live in sibling
modules:

* Instance-level values — [`instance/`](../../instance/README.md)
* Cached queries and CTEs — [`query/`](../../query/README.md)
* Business glossary — [`glossary/`](../../glossary/README.md)
* OSI semantic model — [`osi/`](../../osi/README.md)

## Data Stewards **(Not Implemented)**

Data catalogs allow data stewards to be defined and linked to the appropriate
assets in the database.

Nodes
* `Steward`

Relationships
* `(:Steward)-[:STEWARDS_SCHEMA]->(:Schema)`
* `(:Steward)-[:STEWARDS_TABLE]->(:Table)`
* `(:Steward)-[:STEWARDS_CATEGORY]->(:Category)`
* `(:Steward)-[:STEWARDS_BUSINESS_TERM]->(:BusinessTerm)`

## Rules **(Not Implemented)**

Data catalogs allow for data quality and business rules to be defined and linked
to the appropriate assets. These rules may be returned alongside their
respective data assets to guide the agent in how to use them properly.

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
    * This relationship may be used to identify columns that are impacted by a
      business rule

## Transformations **(Not Implemented)**

`Transform` nodes trace data lineage and how downstream columns are calculated.
These nodes may also contain metadata such as SQL queries, transformation logic
or algorithms run to process the data.

Nodes
* `Transform`

Relationships
* `(:Column)-[:INPUT_TO]->(:Transform)`
* `(:Transform)-[:PRODUCES]->(:Column)`
