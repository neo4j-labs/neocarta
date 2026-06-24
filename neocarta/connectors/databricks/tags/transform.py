"""Transform Databricks governed-tag definitions into governance-tag graph objects.

Mapping (governed tag → governance-tag model, definition layer):

- each governed tag *key* → a :GovernanceTagKey (carrying the tag's description);
- each allowed *value* → a :GovernanceTagValue;
- each (key, value) pair → a (:GovernanceTagKey)-[:HAS_VALUE_OPTION]->(:GovernanceTagValue) edge.

Allowed values carry no description in Databricks, so :GovernanceTagValue nodes are
written name-only — no description is synthesized (the field exists for platforms
like GCP whose tag values do carry descriptions). The instance/assignment layer
(:GovernanceTag + TAGGED_WITH + HAS_DEFINITION) is produced from
``information_schema.*_tags`` and is a planned follow-up; this transformer emits
the definition layer only.
"""

import pandas as pd

from ....data_model.governance import (
    GovernanceTagKey,
    GovernanceTagValue,
    HasValueOption,
)
from ...utils.generate_id import (
    generate_governance_tag_key_id,
    generate_governance_tag_value_id,
)


class DatabricksTagsTransformer:
    """Transformer producing GovernanceTagKey/GovernanceTagValue nodes and their edges."""

    def __init__(self) -> None:
        """Initialize empty node and relationship caches."""
        self.governance_tag_key_nodes: list[GovernanceTagKey] = []
        self.governance_tag_value_nodes: list[GovernanceTagValue] = []
        self.has_value_option_relationships: list[HasValueOption] = []

    def transform_to_governance_tag_key_nodes(
        self, tag_key_info: pd.DataFrame
    ) -> list[GovernanceTagKey]:
        """Build :GovernanceTagKey nodes — one per governed tag key."""
        nodes = [
            GovernanceTagKey(
                id=generate_governance_tag_key_id(row.source, row.tag_key),
                name=row.tag_key,
                description=row.tag_description or None,
            )
            for _, row in tag_key_info.iterrows()
        ]
        self.governance_tag_key_nodes = nodes
        return nodes

    def transform_to_governance_tag_value_nodes(
        self, tag_value_info: pd.DataFrame
    ) -> list[GovernanceTagValue]:
        """Build :GovernanceTagValue nodes — one per allowed value (name only)."""
        nodes = [
            GovernanceTagValue(
                id=generate_governance_tag_value_id(row.source, row.tag_key, row.value_name),
                name=row.value_name,
                description=None,
            )
            for _, row in tag_value_info.iterrows()
        ]
        self.governance_tag_value_nodes = nodes
        return nodes

    def transform_to_has_value_option_relationships(
        self, tag_value_info: pd.DataFrame
    ) -> list[HasValueOption]:
        """Build (:GovernanceTagKey)-[:HAS_VALUE_OPTION]->(:GovernanceTagValue) edges."""
        rels = [
            HasValueOption(
                governance_tag_key_id=generate_governance_tag_key_id(row.source, row.tag_key),
                governance_tag_value_id=generate_governance_tag_value_id(
                    row.source, row.tag_key, row.value_name
                ),
            )
            for _, row in tag_value_info.iterrows()
        ]
        self.has_value_option_relationships = rels
        return rels
