"""Collibra glossary transformer: build Glossary/Category/BusinessTerm subtypes + tags."""

from dataclasses import dataclass

from ....data_model.rdbms import (
    CollibraBusinessTerm,
    CollibraCategory,
    CollibraGlossary,
    CollibraTaggedWith,
    HasBusinessTerm,
    HasCategory,
)
from ....enums import NodeLabel, RelationshipType
from ...utils.generate_id import (
    generate_business_term_id,
    generate_category_id,
    generate_glossary_id,
)
from .extract import CollibraGlossaryExtractor


@dataclass
class _GlossaryContext:
    """Resolved coordinates for a glossary domain."""

    glossary_id: str
    glossary_name: str


@dataclass
class _CategoryContext:
    """Resolved coordinates for a category, used to build term ids/edges."""

    category_id: str
    glossary_name: str
    category_name: str


def _included(label: NodeLabel | RelationshipType, include: list | None) -> bool:
    """Return whether a node/relationship type is selected by an include filter."""
    return include is None or label in include


class CollibraGlossaryTransformer:
    """Convert cached Collibra glossary DataFrames into subtype graph objects."""

    def __init__(self) -> None:
        """Initialise empty node and relationship caches."""
        self.glossary_nodes: list[CollibraGlossary] = []
        self.category_nodes: list[CollibraCategory] = []
        self.business_term_nodes: list[CollibraBusinessTerm] = []
        self.has_category_relationships: list[HasCategory] = []
        self.has_business_term_relationships: list[HasBusinessTerm] = []
        self.tagged_with_relationships: list[CollibraTaggedWith] = []

    def transform_all(
        self,
        extractor: CollibraGlossaryExtractor,
        include_nodes: list[NodeLabel] | None = None,
        include_relationships: list[RelationshipType] | None = None,
    ) -> None:
        """Build all node and relationship objects, honouring the include filters."""
        glossary_context = self._transform_glossaries(extractor, include_nodes)
        category_context = self._transform_categories(
            extractor, glossary_context, include_nodes, include_relationships
        )
        term_ids = self._transform_business_terms(
            extractor, glossary_context, category_context, include_nodes, include_relationships
        )
        self._transform_tags(extractor, term_ids, include_relationships)

    def _transform_glossaries(
        self, extractor: CollibraGlossaryExtractor, include_nodes: list[NodeLabel] | None
    ) -> dict[str, _GlossaryContext]:
        """Build Glossary nodes; return domain_id → _GlossaryContext."""
        emit = _included(NodeLabel.GLOSSARY, include_nodes)
        context: dict[str, _GlossaryContext] = {}
        for row in extractor.glossary_info.to_dict("records"):
            glossary_id = generate_glossary_id(row["domain_name"])
            context[row["domain_id"]] = _GlossaryContext(glossary_id, row["domain_name"])
            if emit:
                self.glossary_nodes.append(
                    CollibraGlossary(
                        id=glossary_id,
                        name=row["domain_name"],
                        description=row["description"],
                        collibra_id=row["domain_id"],
                    )
                )
        return context

    def _transform_categories(
        self,
        extractor: CollibraGlossaryExtractor,
        glossary_context: dict[str, _GlossaryContext],
        include_nodes: list[NodeLabel] | None,
        include_relationships: list[RelationshipType] | None,
    ) -> dict[str, _CategoryContext]:
        """Build Category nodes + HAS_CATEGORY; return category_collibra_id → _CategoryContext."""
        emit_node = _included(NodeLabel.CATEGORY, include_nodes)
        emit_rel = _included(RelationshipType.HAS_CATEGORY, include_relationships)
        context: dict[str, _CategoryContext] = {}
        for row in extractor.category_info.to_dict("records"):
            glossary = glossary_context.get(row["domain_id"])
            if glossary is None:
                continue
            category_id = generate_category_id(glossary.glossary_name, row["asset_name"])
            context[row["asset_id"]] = _CategoryContext(
                category_id, glossary.glossary_name, row["asset_name"]
            )
            if emit_node:
                self.category_nodes.append(
                    CollibraCategory(
                        id=category_id,
                        name=row["asset_name"],
                        description=row["description"],
                        status=row["status"],
                        collibra_id=row["asset_id"],
                    )
                )
            if emit_rel:
                self.has_category_relationships.append(
                    HasCategory(glossary_id=glossary.glossary_id, category_id=category_id)
                )
        return context

    def _transform_business_terms(
        self,
        extractor: CollibraGlossaryExtractor,
        glossary_context: dict[str, _GlossaryContext],
        category_context: dict[str, _CategoryContext],
        include_nodes: list[NodeLabel] | None,
        include_relationships: list[RelationshipType] | None,
    ) -> dict[str, str]:
        """Build BusinessTerm nodes + HAS_BUSINESS_TERM; return term_collibra_id → term_id."""
        emit_node = _included(NodeLabel.BUSINESS_TERM, include_nodes)
        emit_rel = _included(RelationshipType.HAS_BUSINESS_TERM, include_relationships)
        term_ids: dict[str, str] = {}
        for row in extractor.business_term_info.to_dict("records"):
            glossary = glossary_context.get(row["domain_id"])
            if glossary is None:
                continue
            category = category_context.get(row.get("category_collibra_id"))
            # Uncategorised terms fall back to the glossary name as the id's category
            # segment so the id stays stable; no HAS_BUSINESS_TERM edge is emitted.
            category_name = category.category_name if category else glossary.glossary_name
            term_id = generate_business_term_id(
                glossary.glossary_name, category_name, row["asset_name"]
            )
            term_ids[row["asset_id"]] = term_id
            if emit_node:
                self.business_term_nodes.append(
                    CollibraBusinessTerm(
                        id=term_id,
                        name=row["asset_name"],
                        description=row["description"],
                        status=row["status"],
                        collibra_id=row["asset_id"],
                    )
                )
            if emit_rel and category is not None:
                self.has_business_term_relationships.append(
                    HasBusinessTerm(category_id=category.category_id, business_term_id=term_id)
                )
        return term_ids

    def _transform_tags(
        self,
        extractor: CollibraGlossaryExtractor,
        term_ids: dict[str, str],
        include_relationships: list[RelationshipType] | None,
    ) -> None:
        """Build TAGGED_WITH edges (tagged asset UUID → BusinessTerm node id)."""
        if not _included(RelationshipType.TAGGED_WITH, include_relationships):
            return
        for row in extractor.tagged_with_info.to_dict("records"):
            term_id = term_ids.get(row["term_collibra_id"])
            if term_id is None:
                continue
            self.tagged_with_relationships.append(
                CollibraTaggedWith(
                    source_collibra_id=row["source_collibra_id"], business_term_id=term_id
                )
            )
