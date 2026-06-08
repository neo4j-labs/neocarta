"""Collibra schema transformer: build Database/Schema/Table/Column subtype nodes."""

import warnings
from dataclasses import dataclass

from ....data_model.rdbms import (
    CollibraColumn,
    CollibraDatabase,
    CollibraSchema,
    CollibraTable,
    HasColumn,
    HasSchema,
    HasTable,
)
from ....enums import NodeLabel, RelationshipType
from ....warnings import UnresolvedCollibraParentWarning
from ...utils.generate_id import (
    generate_column_id,
    generate_database_id,
    generate_schema_id,
    generate_table_id,
)
from .extract import CollibraSchemaExtractor

_MAX_SKIPPED_PREVIEW = 10


@dataclass
class _TableContext:
    """Resolved coordinates for a table, used to build child column ids."""

    table_id: str
    database_name: str
    schema_name: str
    table_name: str


def _included(label: NodeLabel | RelationshipType, include: list | None) -> bool:
    """Return whether a node/relationship type is selected by an include filter."""
    return include is None or label in include


class CollibraSchemaTransformer:
    """Convert cached Collibra physical-layer DataFrames into subtype graph objects."""

    def __init__(self) -> None:
        """Initialise empty node and relationship caches."""
        self.database_nodes: list[CollibraDatabase] = []
        self.schema_nodes: list[CollibraSchema] = []
        self.table_nodes: list[CollibraTable] = []
        self.column_nodes: list[CollibraColumn] = []
        self.has_schema_relationships: list[HasSchema] = []
        self.has_table_relationships: list[HasTable] = []
        self.has_column_relationships: list[HasColumn] = []

    def transform_all(
        self,
        extractor: CollibraSchemaExtractor,
        include_nodes: list[NodeLabel] | None = None,
        include_relationships: list[RelationshipType] | None = None,
    ) -> None:
        """Build all node and relationship objects, honouring the include filters."""
        community_names = self._transform_communities(extractor, include_nodes)
        domain_context = self._transform_schemas(
            extractor, community_names, include_nodes, include_relationships
        )
        table_context = self._transform_tables(
            extractor, domain_context, include_nodes, include_relationships
        )
        self._transform_columns(extractor, table_context, include_nodes, include_relationships)

    def _transform_communities(
        self, extractor: CollibraSchemaExtractor, include_nodes: list[NodeLabel] | None
    ) -> dict[str, str]:
        """Build Database nodes; return community_id → community_name."""
        names: dict[str, str] = {}
        emit = _included(NodeLabel.DATABASE, include_nodes)
        for row in extractor.community_info.to_dict("records"):
            names[row["community_id"]] = row["community_name"]
            if emit:
                self.database_nodes.append(
                    CollibraDatabase(
                        id=generate_database_id(row["community_name"]),
                        name=row["community_name"],
                        platform="Collibra",
                        service="Collibra Data Intelligence Cloud",
                        description=row["description"],
                        collibra_id=row["community_id"],
                    )
                )
        return names

    def _transform_schemas(
        self,
        extractor: CollibraSchemaExtractor,
        community_names: dict[str, str],
        include_nodes: list[NodeLabel] | None,
        include_relationships: list[RelationshipType] | None,
    ) -> dict[str, tuple[str, str]]:
        """Build Schema nodes + HAS_SCHEMA; return domain_id → (db_name, schema_name)."""
        emit_node = _included(NodeLabel.SCHEMA, include_nodes)
        emit_rel = _included(RelationshipType.HAS_SCHEMA, include_relationships)
        context: dict[str, tuple[str, str]] = {}
        for row in extractor.schema_domain_info.to_dict("records"):
            db_name = community_names.get(row["community_id"], row["community_id"])
            db_id = generate_database_id(db_name)
            schema_id = generate_schema_id(db_name, row["domain_name"])
            context[row["domain_id"]] = (db_name, row["domain_name"])
            if emit_node:
                self.schema_nodes.append(
                    CollibraSchema(
                        id=schema_id,
                        name=row["domain_name"],
                        description=row["description"],
                        collibra_id=row["domain_id"],
                    )
                )
            if emit_rel:
                self.has_schema_relationships.append(
                    HasSchema(database_id=db_id, schema_id=schema_id)
                )
        return context

    def _transform_tables(
        self,
        extractor: CollibraSchemaExtractor,
        domain_context: dict[str, tuple[str, str]],
        include_nodes: list[NodeLabel] | None,
        include_relationships: list[RelationshipType] | None,
    ) -> dict[str, _TableContext]:
        """Build Table nodes + HAS_TABLE; return table_collibra_id → _TableContext."""
        emit_node = _included(NodeLabel.TABLE, include_nodes)
        emit_rel = _included(RelationshipType.HAS_TABLE, include_relationships)
        context: dict[str, _TableContext] = {}
        for row in extractor.table_info.to_dict("records"):
            if row["domain_id"] not in domain_context:
                continue
            db_name, schema_name = domain_context[row["domain_id"]]
            table_id = generate_table_id(db_name, schema_name, row["asset_name"])
            context[row["asset_id"]] = _TableContext(
                table_id, db_name, schema_name, row["asset_name"]
            )
            if emit_node:
                self.table_nodes.append(
                    CollibraTable(
                        id=table_id,
                        name=row["asset_name"],
                        description=row["description"],
                        status=row["status"],
                        collibra_id=row["asset_id"],
                        collibra_asset_type=row["asset_type_name"],
                    )
                )
            if emit_rel:
                self.has_table_relationships.append(
                    HasTable(schema_id=generate_schema_id(db_name, schema_name), table_id=table_id)
                )
        return context

    def _transform_columns(
        self,
        extractor: CollibraSchemaExtractor,
        table_context: dict[str, _TableContext],
        include_nodes: list[NodeLabel] | None,
        include_relationships: list[RelationshipType] | None,
    ) -> None:
        """Build Column nodes + HAS_COLUMN, resolving each column's parent table."""
        emit_node = _included(NodeLabel.COLUMN, include_nodes)
        emit_rel = _included(RelationshipType.HAS_COLUMN, include_relationships)
        skipped: list[str] = []
        for row in extractor.column_info.to_dict("records"):
            parent = table_context.get(row["table_collibra_id"])
            if parent is None:
                # Column whose parent table is out of scope — a stable column id
                # requires its table, so it is skipped (reported below).
                skipped.append(row["asset_name"])
                continue
            column_id = generate_column_id(
                parent.database_name, parent.schema_name, parent.table_name, row["asset_name"]
            )
            if emit_node:
                self.column_nodes.append(
                    CollibraColumn(
                        id=column_id,
                        name=row["asset_name"],
                        description=row["description"],
                        status=row["status"],
                        collibra_id=row["asset_id"],
                        collibra_asset_type=row["asset_type_name"],
                    )
                )
            if emit_rel:
                self.has_column_relationships.append(
                    HasColumn(table_id=parent.table_id, column_id=column_id)
                )
        self._warn_skipped_columns(skipped)

    @staticmethod
    def _warn_skipped_columns(skipped: list[str]) -> None:
        """Emit a single aggregated warning for columns dropped for lack of a parent table."""
        if not skipped:
            return
        preview = ", ".join(sorted(skipped)[:_MAX_SKIPPED_PREVIEW])
        suffix = ", …" if len(skipped) > _MAX_SKIPPED_PREVIEW else ""
        warnings.warn(
            f"Skipped {len(skipped)} Collibra column(s) whose parent table was not in "
            f"scope (a stable column id requires its table): {preview}{suffix}.",
            UnresolvedCollibraParentWarning,
            stacklevel=2,
        )
