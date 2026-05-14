"""Collibra Transformer: converts extracted DataFrames into neocarta model objects."""

from typing import Any

from ...connectors.utils.generate_id import (
    generate_business_term_id,
    generate_catalog_asset_id,
    generate_category_id,
    generate_column_id,
    generate_database_id,
    generate_glossary_id,
    generate_schema_id,
    generate_table_id,
)
from ...data_model.rdbms import (
    BusinessTerm,
    CatalogAsset,
    Category,
    Column,
    Database,
    FlowsInto,
    Glossary,
    HasAsset,
    HasBusinessTerm,
    HasCategory,
    HasColumn,
    HasSchema,
    HasTable,
    Schema,
    Table,
    TaggedWith,
)
from .extract import CollibraExtractor
from .type_mapping import ASSET_TYPE_ALIASES, DOMAIN_TYPE_ALIASES, RELATION_TYPE_ALIASES

# Neocarta type tag → how to look up the default glossary/category context
_TABLE_LIKE = ("Table",)
_COLUMN_LIKE = ("Column",)
_GLOSSARY_LIKE = ("Glossary",)
_SCHEMA_LIKE = ("Schema",)


class CollibraTransformer:
    """
    Transformer that converts Collibra DataFrames into neocarta model objects.

    Consumes the DataFrames produced by ``CollibraExtractor`` and populates
    ``_nodes_cache`` and ``_relationships_cache`` with typed model instances
    ready for ``Neo4jRDBMSLoader``.

    Parameters
    ----------
    extractor : CollibraExtractor
        A fully-extracted Collibra extractor instance.
    """

    def __init__(self, extractor: CollibraExtractor) -> None:
        """Initialise with a populated extractor."""
        self._extractor = extractor
        self._nodes_cache: dict[str, list[Any]] = {
            "database_nodes": [],
            "schema_nodes": [],
            "glossary_nodes": [],
            "table_nodes": [],
            "column_nodes": [],
            "business_term_nodes": [],
            "category_nodes": [],
            "catalog_asset_nodes": [],
        }
        self._relationships_cache: dict[str, list[Any]] = {
            "has_schema_relationships": [],
            "has_table_relationships": [],
            "has_column_relationships": [],
            "has_category_relationships": [],
            "has_business_term_relationships": [],
            "has_asset_relationships": [],
            "tagged_with_relationships": [],
            "flows_into_relationships": [],
        }

        # Build attribute lookup: asset_id → dict of attribute_type → value
        self._attribute_map: dict[str, dict[str, str]] = {}
        attr_df = extractor.attribute_info
        if not attr_df.empty:
            for _, row in attr_df.iterrows():
                aid = row["asset_id"]
                self._attribute_map.setdefault(aid, {})
                self._attribute_map[aid][row["attribute_type"].lower()] = row["value"] or ""

        # Build domain info lookup: domain_id → row
        self._domain_map: dict[str, dict] = {}
        domain_df = extractor.domain_info
        if not domain_df.empty:
            self._domain_map = {r["domain_id"]: r for r in domain_df.to_dict("records")}

        # Resolve domain type IDs → neocarta tag (Schema or Glossary)
        self._domain_neo_type: dict[str, str] = {}
        for did, domain in self._domain_map.items():
            type_name = domain["domain_type_name"].lower()
            neo_type = DOMAIN_TYPE_ALIASES.get(type_name, "Schema")  # default to Schema
            self._domain_neo_type[did] = neo_type

        # Build community→database_id lookup
        self._community_to_db: dict[str, str] = {}
        comm_df = extractor.community_info
        if not comm_df.empty:
            for _, row in comm_df.iterrows():
                self._community_to_db[row["community_id"]] = generate_database_id(
                    row["community_name"]
                )

        # Build domain_id→Schema/Glossary id lookup (set after transform_domains)
        self._domain_node_id: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Attribute helper
    # ------------------------------------------------------------------

    def _attr(self, asset_id: str, *keys: str) -> str | None:
        """Return the first matching attribute value for an asset."""
        attrs = self._attribute_map.get(asset_id, {})
        for key in keys:
            val = attrs.get(key.lower())
            if val:
                return val
        return None

    # ------------------------------------------------------------------
    # Transform methods
    # ------------------------------------------------------------------

    def transform_communities(self) -> None:
        """Convert community rows to Database nodes and HAS_SCHEMA setup."""
        comm_df = self._extractor.community_info
        if comm_df.empty:
            return

        for _, row in comm_df.iterrows():
            db_id = generate_database_id(row["community_name"])
            db = Database(
                id=db_id,
                name=row["community_name"],
                platform="Collibra",
                service="Collibra Data Intelligence Cloud",
                description=row.get("description"),
            )
            self._nodes_cache["database_nodes"].append(db)

    def transform_domains(self) -> None:
        """Convert domain rows to Schema or Glossary nodes."""
        domain_df = self._extractor.domain_info
        if domain_df.empty:
            return

        for _, row in domain_df.iterrows():
            cid = row["community_id"]
            db_id = self._community_to_db.get(cid, generate_database_id(cid))
            domain_name = row["domain_name"]
            neo_type = self._domain_neo_type.get(row["domain_id"], "Schema")

            if neo_type == "Glossary":
                gls_id = generate_glossary_id(domain_name)
                self._domain_node_id[row["domain_id"]] = gls_id
                gls = Glossary(
                    id=gls_id,
                    name=domain_name,
                    description=row.get("description"),
                    collibra_id=row["domain_id"],
                )
                self._nodes_cache["glossary_nodes"].append(gls)
                # HAS_SCHEMA links Database → Glossary (using same rel type for now)
                self._relationships_cache["has_schema_relationships"].append(
                    HasSchema(database_id=db_id, schema_id=gls_id)
                )
            else:
                sch_id = generate_schema_id(db_id, domain_name)
                self._domain_node_id[row["domain_id"]] = sch_id
                sch = Schema(id=sch_id, name=domain_name, description=row.get("description"))
                self._nodes_cache["schema_nodes"].append(sch)
                self._relationships_cache["has_schema_relationships"].append(
                    HasSchema(database_id=db_id, schema_id=sch_id)
                )

    def transform_assets(self) -> None:
        """Convert asset rows to the appropriate neocarta node type."""
        asset_df = self._extractor.asset_info
        if asset_df.empty:
            return

        for _, row in asset_df.iterrows():
            asset_id = row["asset_id"]
            asset_name = row["asset_name"]
            domain_id = row["domain_id"]
            type_name = row["asset_type_name"].lower()
            neo_type = ASSET_TYPE_ALIASES.get(type_name)
            status = row.get("status")
            description = self._attr(asset_id, "description", "definition", "note")
            parent_node_id = self._domain_node_id.get(domain_id, "")

            # Also resolve domain context for IDs
            domain_row = self._domain_map.get(domain_id, {})
            domain_name = domain_row.get("domain_name", domain_id)
            community_id = domain_row.get("community_id", "")
            comm_df = self._extractor.community_info
            community_name = ""
            if not comm_df.empty and community_id:
                match = comm_df[comm_df["community_id"] == community_id]
                if not match.empty:
                    community_name = match.iloc[0]["community_name"]

            if neo_type == "Table":
                node_id = generate_table_id(community_name, domain_name, asset_name)
                node = Table(
                    id=node_id,
                    name=asset_name,
                    description=description,
                    status=status,
                    collibra_id=asset_id,
                    collibra_asset_type=row["asset_type_name"],
                )
                self._nodes_cache["table_nodes"].append(node)
                self._relationships_cache["has_table_relationships"].append(
                    HasTable(schema_id=parent_node_id, table_id=node_id)
                )

            elif neo_type == "Column":
                node_id = generate_column_id(community_name, domain_name, "unknown", asset_name)
                node = Column(
                    id=node_id,
                    name=asset_name,
                    description=description,
                    status=status,
                    collibra_id=asset_id,
                )
                self._nodes_cache["column_nodes"].append(node)

            elif neo_type == "BusinessTerm":
                gls_name = domain_name
                cat_name = "default"
                node_id = generate_business_term_id(gls_name, cat_name, asset_name)
                node = BusinessTerm(
                    id=node_id,
                    name=asset_name,
                    description=description,
                    status=status,
                    collibra_id=asset_id,
                )
                self._nodes_cache["business_term_nodes"].append(node)

            elif neo_type == "Category":
                gls_name = domain_name
                node_id = generate_category_id(gls_name, asset_name)
                node = Category(
                    id=node_id,
                    name=asset_name,
                    description=description,
                    status=status,
                    collibra_id=asset_id,
                )
                self._nodes_cache["category_nodes"].append(node)

            else:
                # Unknown type → CatalogAsset
                node_id = generate_catalog_asset_id(asset_id)
                node = CatalogAsset(  # type: ignore[assignment]
                    id=node_id,
                    name=asset_name,
                    description=description,
                    status=status,
                    collibra_id=asset_id,
                    asset_type=row["asset_type_name"],
                    domain_id=parent_node_id,
                )
                self._nodes_cache["catalog_asset_nodes"].append(node)
                if parent_node_id:
                    self._relationships_cache["has_asset_relationships"].append(
                        HasAsset(parent_id=parent_node_id, asset_id=node_id)
                    )

    def transform_relations(self) -> None:
        """Convert relation rows to neocarta relationship objects."""
        rel_df = self._extractor.relation_info
        if rel_df.empty:
            return

        # Build lookup: collibra_id → neocarta node_id
        id_map = self._build_collibra_id_map()

        for _, row in rel_df.iterrows():
            type_name = row["relation_type_name"].lower()
            neo_rel = RELATION_TYPE_ALIASES.get(type_name)
            src_neo = id_map.get(row["source_id"])
            tgt_neo = id_map.get(row["target_id"])

            if not src_neo or not tgt_neo or not neo_rel:
                continue

            if neo_rel == "HAS_COLUMN":
                self._relationships_cache["has_column_relationships"].append(
                    HasColumn(table_id=src_neo, column_id=tgt_neo)
                )
            elif neo_rel == "TAGGED_WITH":
                self._relationships_cache["tagged_with_relationships"].append(
                    TaggedWith(entity_id=src_neo, business_term_id=tgt_neo)
                )
            elif neo_rel == "HAS_CATEGORY":
                self._relationships_cache["has_category_relationships"].append(
                    HasCategory(glossary_id=src_neo, category_id=tgt_neo)
                )
            elif neo_rel == "HAS_BUSINESS_TERM":
                self._relationships_cache["has_business_term_relationships"].append(
                    HasBusinessTerm(category_id=src_neo, business_term_id=tgt_neo)
                )

    def transform_lineage(self) -> None:
        """Convert lineage rows to FlowsInto relationship objects."""
        lineage_df = self._extractor.lineage_info
        if lineage_df.empty:
            return

        id_map = self._build_collibra_id_map()
        for _, row in lineage_df.iterrows():
            src_neo = id_map.get(row["source_id"])
            tgt_neo = id_map.get(row["target_id"])
            if src_neo and tgt_neo:
                self._relationships_cache["flows_into_relationships"].append(
                    FlowsInto(
                        source_id=src_neo,
                        target_id=tgt_neo,
                        lineage_type=row.get("lineage_type"),
                    )
                )

    def _build_collibra_id_map(self) -> dict[str, str]:
        """Build a collibra_id → neocarta node_id lookup from all produced nodes."""
        id_map: dict[str, str] = {}
        for node_list in self._nodes_cache.values():
            for node in node_list:
                cid = getattr(node, "collibra_id", None)
                if cid:
                    id_map[cid] = node.id
        return id_map

    # ------------------------------------------------------------------
    # Cache accessors
    # ------------------------------------------------------------------

    @property
    def database_nodes(self) -> list[Database]:
        """Transformed Database nodes."""
        return self._nodes_cache["database_nodes"]  # type: ignore[return-value]

    @property
    def schema_nodes(self) -> list[Schema]:
        """Transformed Schema nodes."""
        return self._nodes_cache["schema_nodes"]  # type: ignore[return-value]

    @property
    def glossary_nodes(self) -> list[Glossary]:
        """Transformed Glossary nodes."""
        return self._nodes_cache["glossary_nodes"]  # type: ignore[return-value]

    @property
    def table_nodes(self) -> list[Table]:
        """Transformed Table nodes."""
        return self._nodes_cache["table_nodes"]  # type: ignore[return-value]

    @property
    def column_nodes(self) -> list[Column]:
        """Transformed Column nodes."""
        return self._nodes_cache["column_nodes"]  # type: ignore[return-value]

    @property
    def business_term_nodes(self) -> list[BusinessTerm]:
        """Transformed BusinessTerm nodes."""
        return self._nodes_cache["business_term_nodes"]  # type: ignore[return-value]

    @property
    def category_nodes(self) -> list[Category]:
        """Transformed Category nodes."""
        return self._nodes_cache["category_nodes"]  # type: ignore[return-value]

    @property
    def catalog_asset_nodes(self) -> list[CatalogAsset]:
        """Transformed CatalogAsset nodes."""
        return self._nodes_cache["catalog_asset_nodes"]  # type: ignore[return-value]

    @property
    def has_schema_relationships(self) -> list[HasSchema]:
        """Transformed HAS_SCHEMA relationships."""
        return self._relationships_cache["has_schema_relationships"]  # type: ignore[return-value]

    @property
    def has_table_relationships(self) -> list[HasTable]:
        """Transformed HAS_TABLE relationships."""
        return self._relationships_cache["has_table_relationships"]  # type: ignore[return-value]

    @property
    def has_column_relationships(self) -> list[HasColumn]:
        """Transformed HAS_COLUMN relationships."""
        return self._relationships_cache["has_column_relationships"]  # type: ignore[return-value]

    @property
    def has_category_relationships(self) -> list[HasCategory]:
        """Transformed HAS_CATEGORY relationships."""
        return self._relationships_cache["has_category_relationships"]  # type: ignore[return-value]

    @property
    def has_business_term_relationships(self) -> list[HasBusinessTerm]:
        """Transformed HAS_BUSINESS_TERM relationships."""
        return self._relationships_cache["has_business_term_relationships"]  # type: ignore[return-value]

    @property
    def has_asset_relationships(self) -> list[HasAsset]:
        """Transformed HAS_ASSET relationships."""
        return self._relationships_cache["has_asset_relationships"]  # type: ignore[return-value]

    @property
    def tagged_with_relationships(self) -> list[TaggedWith]:
        """Transformed TAGGED_WITH relationships."""
        return self._relationships_cache["tagged_with_relationships"]  # type: ignore[return-value]

    @property
    def flows_into_relationships(self) -> list[FlowsInto]:
        """Transformed FLOWS_INTO relationships."""
        return self._relationships_cache["flows_into_relationships"]  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def transform_all(self) -> None:
        """Run all transformation steps in dependency order."""
        self.transform_communities()
        self.transform_domains()
        self.transform_assets()
        self.transform_relations()
        self.transform_lineage()
