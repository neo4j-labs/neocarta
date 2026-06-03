"""Transform Dataplex glossary data into glossary graph nodes/relationships."""

import pandas as pd

from ....data_model.rdbms import (
    BusinessTerm,
    Category,
    Glossary,
    HasBusinessTerm,
    HasCategory,
    TaggedWith,
)
from ...utils.generate_id import (
    generate_business_term_id,
    generate_category_id,
    generate_glossary_id,
)
from ..utils import parse_business_term_slug, parse_category_slug


class DataplexGlossaryTransformer:
    """
    Transformer producing Glossary/Category/BusinessTerm nodes and their relationships,
    including catalog↔glossary TAGGED_WITH edges.
    """

    def __init__(self) -> None:
        """Initialize empty node and relationship caches."""
        self.glossary_nodes: list[Glossary] = []
        self.category_nodes: list[Category] = []
        self.business_term_nodes: list[BusinessTerm] = []
        self.has_category_relationships: list[HasCategory] = []
        self.has_business_term_relationships: list[HasBusinessTerm] = []
        self.column_tagged_with_relationships: list[TaggedWith] = []
        self.table_tagged_with_relationships: list[TaggedWith] = []

    def transform_to_glossary_nodes(self, glossary_info: pd.DataFrame) -> list[Glossary]:
        """Build :Glossary nodes from one row per glossary."""
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
        """Build :Category nodes from one row per (glossary, category)."""
        nodes = [
            Category(
                id=generate_category_id(row.glossary_id, parse_category_slug(row.category_id)),
                name=parse_category_slug(row.category_id),
                description=None,
                resource_path=row.category_id,
            )
            for _, row in category_info.iterrows()
        ]
        self.category_nodes = nodes
        return nodes

    def transform_to_business_term_nodes(
        self, business_term_info: pd.DataFrame
    ) -> list[BusinessTerm]:
        """Build :BusinessTerm nodes from one row per term."""
        nodes = [
            BusinessTerm(
                id=generate_business_term_id(
                    row.glossary_id,
                    parse_category_slug(row.category_id),
                    parse_business_term_slug(row.term_id),
                ),
                name=row.term_name,
                description=row.term_description,
                resource_path=row.term_id,
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
                category_id=generate_category_id(
                    row.glossary_id, parse_category_slug(row.category_id)
                ),
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
                category_id=generate_category_id(
                    row.glossary_id, parse_category_slug(row.category_id)
                ),
                business_term_id=generate_business_term_id(
                    row.glossary_id,
                    parse_category_slug(row.category_id),
                    parse_business_term_slug(row.term_id),
                ),
            )
            for _, row in business_term_info.iterrows()
        ]
        self.has_business_term_relationships = rels
        return rels

    def transform_to_column_tagged_with_relationships(
        self, column_term_info: pd.DataFrame
    ) -> list[TaggedWith]:
        """Build (:Column)-[:TAGGED_WITH]->(:BusinessTerm) edges from entry links."""
        rels = [
            TaggedWith(
                source_label="Column",
                source_id=row.entity_id,
                business_term_id=row.business_term_id,
            )
            for _, row in column_term_info.iterrows()
        ]
        self.column_tagged_with_relationships = rels
        return rels

    def transform_to_table_tagged_with_relationships(
        self, table_term_info: pd.DataFrame
    ) -> list[TaggedWith]:
        """Build (:Table)-[:TAGGED_WITH]->(:BusinessTerm) edges from entry links."""
        rels = [
            TaggedWith(
                source_label="Table",
                source_id=row.entity_id,
                business_term_id=row.business_term_id,
            )
            for _, row in table_term_info.iterrows()
        ]
        self.table_tagged_with_relationships = rels
        return rels
