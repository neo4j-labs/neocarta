# Instance Data Model

Instance-level data: the actual values observed in the source data. Value nodes
provide example values and enums that augment the database context. For example,
upon matching a `Column`, `k` values may be returned as examples by traversing
to related `Value` nodes. If values are constrained to a set of options, these
may be provided as an enum in the context to provide additional guidance.

Nodes
* [`Value`](./models.py#L8)
    * Represents a single unique value drawn from the source data, cast to a
      string
    * The node is source-agnostic; the originating entity is recorded by the
      relationship rather than on the node
    * Values are unique on the column level within the graph

Relationships
* [`(:Column)-[:HAS_VALUE]->(:Value)`](./models.py#L22)
    * Defines a value's parent column

> The LPG `(:Property)-[:HAS_VALUE]->(:Value)` edge is not yet implemented; see
> [`schema/lpg`](../schema/lpg/README.md).
