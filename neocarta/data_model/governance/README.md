# Governance Data Model

Data platforms attach *governance tags* — controlled-vocabulary labels for
policy, classification, or ownership — to their objects: Databricks Unity Catalog
governed tags, Snowflake object tags, GCP resource Tags. Unlike a business
glossary, a tag's values are controls rather than vocabulary
(`sensitivity ∈ {pii, non_pii}` is not a set of business *terms*), so they are
modelled in their own vendor-neutral component instead of
`Glossary`/`Category`/`BusinessTerm`.

The model has two layers. The **definition** layer describes which tags exist,
what they mean, and which values are allowed — it is the agent-searchable surface
(a full-text index, and optionally a vector index, over `GovernanceTagKey`). The
**instance** layer records where tags are applied; comparing instances against
definitions enables tag validation. The definition layer is optional: free-form
tags (a Snowflake tag with no allowed values, a BigQuery label) have instances
but no definition, so the instance layer stands alone.

Nodes
* [`GovernanceTagKey`](./models.py#L34)
    * The definition of a tag key — its `name`, optional `description`, and
      optional `embedding`
    * Ids are namespaced by source (metastore/account) so keys don't collide
      across accounts or vendors
* [`GovernanceTagValue`](./models.py#L54)
    * One allowed value of a tag key
    * `description` is optional — GCP tag values carry descriptions; Databricks
      and Snowflake values are bare
* [`GovernanceTag`](./models.py#L72)
    * One applied (key, value) assignment — non-unique across the graph (one per
      tagged object), with `key`/`value` denormalised for single-hop lookups

Relationships
* [`(:GovernanceTagKey)-[:HAS_VALUE_OPTION]->(:GovernanceTagValue)`](./models.py#L88)
    * Declares an allowed value of a governed tag key
* [`(:GovernanceTag)-[:HAS_DEFINITION]->(:GovernanceTagValue)`](./models.py#L102)
    * Links an applied tag to the value definition it satisfies; present only
      when the value is governed, so a missing link marks a free-form value
* [`(:Column|:Table|:Schema)-[:TAGGED_WITH]->(:GovernanceTag)`](./models.py#L119)
    * Records that an entity carries a governance tag, via the `source_label`
      discriminator. Shares the `TAGGED_WITH` type with the glossary's
      `…->(:BusinessTerm)` edge but targets a different node label
