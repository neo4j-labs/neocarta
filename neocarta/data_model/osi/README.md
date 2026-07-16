# OSI Semantic Model Data Model

The [Open Semantic Interchange (OSI)](https://github.com/open-semantic-interchange/OSI)
connector extends the relational structural core with semantic-model nodes.
These reuse the core `Database` / `Schema` and add OSI subtypes that carry extra
metadata. See the [OSI connector README](../../connectors/osi/README.md) for the
full data model diagram and behavioral notes.

The OSI subtypes inherit from the relational structural models in
[`schema/rdbms`](../schema/rdbms/README.md): `OsiTable(Table)` and
`OsiColumn(Column)`.

Nodes
* [`Domain`](./models.py#L15) / [`OsiSemanticModel`](./models.py#L26)
    * A semantic grouping of data assets; `OsiSemanticModel` is a `Domain`
      subtype representing a full OSI spec instance, stored as a
      `(:Domain&OsiSemanticModel)` node
* [`OsiTable`](./models.py#L38)
    * A `Table` subtype with OSI key metadata (`source`, `primary_key`,
      `unique_keys`), stored as `(:Table&OsiTable)`
* [`OsiColumn`](./models.py#L65)
    * A `Column` subtype with OSI display metadata (`label`,
      `is_time_dimension`), stored as `(:Column&OsiColumn)`
* [`Metric`](./models.py#L83)
    * A measurable quantity in an OSI semantic model
* [`Join`](./models.py#L135)
    * A join definition between two tables (`from_columns` / `to_columns`
      preserve composite-key ordering)
* [`Expression`](./models.py#L125)
    * A dialect-specific computation expression
* [`Aspect`](./models.py#L94) / [`OsiAiContext`](./models.py#L103) / [`OsiCustomExtensions`](./models.py#L116)
    * Additional context attached to entities; `OsiAiContext` carries
      agent-facing context and `OsiCustomExtensions` carries vendor-specific
      metadata, both as JSON-encoded strings

Relationships
* [`(:Domain)-[:HAS_TABLE]->(:Table)`](./models.py#L211)
    * A semantic model owns its datasets (tables) directly
* [`(:Domain)-[:HAS_QUERY]->(:Query)`](./models.py#L227)
    * OSI datasets whose `source` is a SQL query are stored as
      [`Query`](../query/README.md) nodes
* [`(:Domain)-[:HAS_METRIC]->(:Metric)`](./models.py#L201)
* [`(:Join)-[:HAS_SOURCE_TABLE]->(:Table)`](./models.py#L241) / [`(:Join)-[:HAS_TARGET_TABLE]->(:Table)`](./models.py#L251)
* [`(:Column)-[:USED_IN_JOIN]->(:Join)`](./models.py#L177)
* [`(:Column|:Metric)-[:HAS_EXPRESSION]->(:Expression)`](./models.py#L187)
* [`(:Schema|:Table|:Column|:Query|:Metric|:Join|:Domain)-[:HAS_ASPECT]->(:Aspect)`](./models.py#L158)
