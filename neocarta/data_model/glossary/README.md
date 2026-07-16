# Glossary Data Model

Data catalogs allow business terms to be defined and linked to tables and
columns. This allows relationships to be inferred by shared business terms
across assets. For example `TableA.customer_id` and `TableB.cstmr_id` both
tagged with the business term "Customer ID" implies those columns can be used to
join their respective tables.

Nodes
* [`Glossary`](./models.py#L8)
    * The glossary containing categories and business terms
    * Carries an optional `resource_path` (e.g. the Dataplex resource name)
* [`Category`](./models.py#L20)
    * Contains information about a category in the glossary
    * Carries an optional `resource_path`
* [`BusinessTerm`](./models.py#L32)
    * A leaf level term in the glossary
    * Defines a globally recognized term across databases in the system
    * Carries an optional `resource_path`

Relationships
* [`(:Glossary)-[:HAS_CATEGORY]->(:Category)`](./models.py#L49)
    * Defines the glossary to category hierarchy
* [`(:Category)-[:HAS_BUSINESS_TERM]->(:BusinessTerm)`](./models.py#L59)
    * Defines the category to business term hierarchy
* [`(:Column|:Table|:Schema|:Metric)-[:TAGGED_WITH]->(:BusinessTerm)`](./models.py#L69)
    * Defines that an entity (column, table, schema, or metric) is tagged with a
      business term, via the `source_label` discriminator
    * Columns tagged with the same business term may be used to join their
      respective tables
