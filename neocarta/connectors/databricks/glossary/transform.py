"""Transform Databricks governed-tag definitions into glossary graph objects.

Mapping (governed tag → glossary model):

- the synthesized account-level glossary → one :Glossary node;
- each governed tag *key* → a :Category (carrying the tag's description);
- each allowed *value* → a :BusinessTerm.

Allowed values carry no description in Databricks, so :BusinessTerm nodes are
written name-only — no description is synthesized. No ``TAGGED_WITH`` edges are
produced in v1 (assignments are a planned follow-up).
"""

import pandas as pd

from ....data_model.glossary import (
    BusinessTerm,
    Category,
    Glossary,
    HasBusinessTerm,
    HasCategory,
)
from ...utils.generate_id import (
    generate_business_term_id,
    generate_category_id,
    generate_glossary_id,
)


class DatabricksGlossaryTransformer:
    """Transformer producing Glossary/Category/BusinessTerm nodes and their edges."""

    def __init__(self) -> None:
        """Initialize empty node and relationship caches."""
        self.glossary_nodes: list[Glossary] = []
        self.category_nodes: list[Category] = []
        self.business_term_nodes: list[BusinessTerm] = []
        self.has_category_relationships: list[HasCategory] = []
        self.has_business_term_relationships: list[HasBusinessTerm] = []

    def transform_to_glossary_nodes(self, glossary_info: pd.DataFrame) -> list[Glossary]:
        """Build the single :Glossary node for the account's governed tags."""
        nodes = [
            Glossary(
                id=generate_glossary_id(row.glossary_id),
                name=row.glossary_name,
                description=None,
                resource_path=row.glossary_resource_path,
            )
            for _, row in glossary_info.iterrows()
        ]
        self.glossary_nodes = nodes
        return nodes

    def transform_to_category_nodes(self, category_info: pd.DataFrame) -> list[Category]:
        """Build :Category nodes — one per governed tag key."""
        nodes = [
            Category(
                id=generate_category_id(row.glossary_id, row.tag_key),
                name=row.tag_key,
                description=row.tag_description or None,
                resource_path=row.tag_policy_id,
            )
            for _, row in category_info.iterrows()
        ]
        self.category_nodes = nodes
        return nodes

    def transform_to_business_term_nodes(
        self, business_term_info: pd.DataFrame
    ) -> list[BusinessTerm]:
        """Build :BusinessTerm nodes — one per allowed value (name only)."""
        nodes = [
            BusinessTerm(
                id=generate_business_term_id(row.glossary_id, row.tag_key, row.value_name),
                name=row.value_name,
                description=None,
                resource_path=None,
            )
            for _, row in business_term_info.iterrows()
        ]
        self.business_term_nodes = nodes
        return nodes

    def transform_to_has_category_relationships(
        self, category_info: pd.DataFrame
    ) -> list[HasCategory]:
        """Build (:Glossary)-[:HAS_CATEGORY]->(:Category) edges."""
        rels = [
            HasCategory(
                glossary_id=generate_glossary_id(row.glossary_id),
                category_id=generate_category_id(row.glossary_id, row.tag_key),
            )
            for _, row in category_info.iterrows()
        ]
        self.has_category_relationships = rels
        return rels

    def transform_to_has_business_term_relationships(
        self, business_term_info: pd.DataFrame
    ) -> list[HasBusinessTerm]:
        """Build (:Category)-[:HAS_BUSINESS_TERM]->(:BusinessTerm) edges."""
        rels = [
            HasBusinessTerm(
                category_id=generate_category_id(row.glossary_id, row.tag_key),
                business_term_id=generate_business_term_id(
                    row.glossary_id, row.tag_key, row.value_name
                ),
            )
            for _, row in business_term_info.iterrows()
        ]
        self.has_business_term_relationships = rels
        return rels
