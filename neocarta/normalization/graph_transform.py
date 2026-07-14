"""Turn a normalized ``InformationSchemaTable`` into RDBMS graph models.

``NormalizedGraphTransformer`` is the single place in the EKL pipeline where
deterministic ids are generated and hierarchy/reference edges are derived. It
consumes the flat, name-parts-only records produced by a
:class:`~neocarta.normalization.normalizer.MetadataNormalizer` and builds exactly
the graph nodes/relationships that the bespoke per-connector transformers produce
today, populating the same ``NodesCache`` / ``RelationshipsCache`` under the same
keys and exposing the same accessors — so a connector can be rewired onto the
shared pipeline with no change to the graph it emits.

Scope is the relational (``InformationSchemaTable``) family only: ``Database`` /
``Schema`` / ``Table`` / ``Column`` / ``Value`` nodes and ``HasSchema`` /
``HasTable`` / ``HasColumn`` / ``References`` / ``HasValue`` relationships. Other
normalized families (glossary, governance, query/lineage, OSI) are added by later
PRs as additional handlers.

Consumers import this class from the submodule
(``from neocarta.normalization.graph_transform import NormalizedGraphTransformer``);
it is intentionally not re-exported from ``neocarta.normalization``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..connectors.models import NodesCache, RelationshipsCache
from ..connectors.utils.generate_id import (
    generate_column_id,
    generate_database_id,
    generate_schema_id,
    generate_table_id,
    generate_value_id,
)
from ..data_model.instance import HasValue, Value
from ..data_model.schema.rdbms import (
    Column,
    Database,
    HasColumn,
    HasSchema,
    HasTable,
    References,
    Schema,
    Table,
)

if TYPE_CHECKING:
    from ..data_model.normalized import (
        ColumnRecord,
        DatabaseRecord,
        InformationSchemaTable,
        ReferenceRecord,
        SchemaRecord,
        TableRecord,
        ValueRecord,
    )


class NormalizedGraphTransformer:
    """Build RDBMS graph models and ids from a normalized ``InformationSchemaTable``.

    Generates every deterministic id (via ``neocarta.connectors.utils.generate_id``)
    and derives every edge from the records' shared name-parts, so an edge's
    endpoint ids always match the node ids. The two source→graph field renames
    (``data_type`` → ``type``, ``is_nullable`` → ``nullable``) happen here; all
    other value coercion (blank → ``None``, ``"YES"``/``"NO"`` → ``bool``,
    platform/service upper-casing) is owned by the record and graph-model
    validators, so record values are passed straight through. No embedding is ever
    written — records carry none and nodes leave ``embedding=None``.
    """

    def __init__(self) -> None:
        """Initialize the transformer with empty node and relationship caches."""
        self._node_cache: NodesCache = NodesCache()
        self._relationships_cache: RelationshipsCache = RelationshipsCache()

    # -- Node accessors --------------------------------------------------------

    @property
    def database_nodes(self) -> list[Database]:
        """list[Database]: The transformed database nodes."""
        return self._node_cache.get("database_nodes", [])

    @property
    def schema_nodes(self) -> list[Schema]:
        """list[Schema]: The transformed schema nodes."""
        return self._node_cache.get("schema_nodes", [])

    @property
    def table_nodes(self) -> list[Table]:
        """list[Table]: The transformed table nodes."""
        return self._node_cache.get("table_nodes", [])

    @property
    def column_nodes(self) -> list[Column]:
        """list[Column]: The transformed column nodes."""
        return self._node_cache.get("column_nodes", [])

    @property
    def value_nodes(self) -> list[Value]:
        """list[Value]: The transformed value nodes."""
        return self._node_cache.get("value_nodes", [])

    # -- Relationship accessors ------------------------------------------------

    @property
    def has_schema_relationships(self) -> list[HasSchema]:
        """list[HasSchema]: The transformed database→schema relationships."""
        return self._relationships_cache.get("has_schema_relationships", [])

    @property
    def has_table_relationships(self) -> list[HasTable]:
        """list[HasTable]: The transformed schema→table relationships."""
        return self._relationships_cache.get("has_table_relationships", [])

    @property
    def has_column_relationships(self) -> list[HasColumn]:
        """list[HasColumn]: The transformed table→column relationships."""
        return self._relationships_cache.get("has_column_relationships", [])

    @property
    def references_relationships(self) -> list[References]:
        """list[References]: The transformed column→column foreign-key relationships."""
        return self._relationships_cache.get("references_relationships", [])

    @property
    def has_value_relationships(self) -> list[HasValue]:
        """list[HasValue]: The transformed column→value relationships."""
        return self._relationships_cache.get("has_value_relationships", [])

    # -- Transform -------------------------------------------------------------

    def transform(self, metadata: InformationSchemaTable) -> None:
        """Build all relational nodes/relationships and populate both caches.

        Parameters
        ----------
        metadata : InformationSchemaTable
            The normalized container of flat records to transform. Any of its six
            record lists may be empty, in which case the corresponding cache entry
            is set to an empty list.
        """
        self._node_cache["database_nodes"] = self._build_database_nodes(metadata.databases)
        self._node_cache["schema_nodes"] = self._build_schema_nodes(metadata.schemas)
        self._node_cache["table_nodes"] = self._build_table_nodes(metadata.tables)
        self._node_cache["column_nodes"] = self._build_column_nodes(metadata.columns)
        self._node_cache["value_nodes"] = self._build_value_nodes(metadata.values)

        self._relationships_cache["has_schema_relationships"] = (
            self._build_has_schema_relationships(metadata.schemas)
        )
        self._relationships_cache["has_table_relationships"] = self._build_has_table_relationships(
            metadata.tables
        )
        self._relationships_cache["has_column_relationships"] = (
            self._build_has_column_relationships(metadata.columns)
        )
        self._relationships_cache["references_relationships"] = (
            self._build_references_relationships(metadata.references)
        )
        self._relationships_cache["has_value_relationships"] = self._build_has_value_relationships(
            metadata.values
        )

    # -- Node builders ---------------------------------------------------------

    @staticmethod
    def _build_database_nodes(records: list[DatabaseRecord]) -> list[Database]:
        """Build ``Database`` nodes from database records."""
        return [
            Database(
                id=generate_database_id(record.database_name),
                name=record.database_name,
                platform=record.platform,
                service=record.service,
                description=record.description,
            )
            for record in records
        ]

    @staticmethod
    def _build_schema_nodes(records: list[SchemaRecord]) -> list[Schema]:
        """Build ``Schema`` nodes from schema records."""
        return [
            Schema(
                id=generate_schema_id(record.database_name, record.schema_name),
                name=record.schema_name,
                description=record.description,
            )
            for record in records
        ]

    @staticmethod
    def _build_table_nodes(records: list[TableRecord]) -> list[Table]:
        """Build ``Table`` nodes from table records (``table_type`` is not a graph property)."""
        return [
            Table(
                id=generate_table_id(record.database_name, record.schema_name, record.table_name),
                name=record.table_name,
                description=record.description,
            )
            for record in records
        ]

    @staticmethod
    def _build_column_nodes(records: list[ColumnRecord]) -> list[Column]:
        """Build ``Column`` nodes from column records.

        Applies the two source→graph field renames (``data_type`` → ``type``,
        ``is_nullable`` → ``nullable``) and passes ``is_primary_key`` /
        ``is_foreign_key`` through unchanged (``ordinal_position`` is not a graph
        property).
        """
        return [
            Column(
                id=generate_column_id(
                    record.database_name,
                    record.schema_name,
                    record.table_name,
                    record.column_name,
                ),
                name=record.column_name,
                description=record.description,
                type=record.data_type,
                nullable=record.is_nullable,
                is_primary_key=record.is_primary_key,
                is_foreign_key=record.is_foreign_key,
            )
            for record in records
        ]

    @staticmethod
    def _build_value_nodes(records: list[ValueRecord]) -> list[Value]:
        """Build ``Value`` nodes from value records.

        The value segment of the id is md5-hashed by ``generate_value_id``, so the
        id matches the value id the extractor pre-builds today.
        """
        return [
            Value(
                id=generate_value_id(
                    record.database_name,
                    record.schema_name,
                    record.table_name,
                    record.column_name,
                    record.value,
                ),
                value=record.value,
            )
            for record in records
        ]

    # -- Relationship builders -------------------------------------------------

    @staticmethod
    def _build_has_schema_relationships(records: list[SchemaRecord]) -> list[HasSchema]:
        """Build database→schema relationships, one per schema record."""
        return [
            HasSchema(
                database_id=generate_database_id(record.database_name),
                schema_id=generate_schema_id(record.database_name, record.schema_name),
            )
            for record in records
        ]

    @staticmethod
    def _build_has_table_relationships(records: list[TableRecord]) -> list[HasTable]:
        """Build schema→table relationships, one per table record."""
        return [
            HasTable(
                schema_id=generate_schema_id(record.database_name, record.schema_name),
                table_id=generate_table_id(
                    record.database_name, record.schema_name, record.table_name
                ),
            )
            for record in records
        ]

    @staticmethod
    def _build_has_column_relationships(records: list[ColumnRecord]) -> list[HasColumn]:
        """Build table→column relationships, one per column record."""
        return [
            HasColumn(
                table_id=generate_table_id(
                    record.database_name, record.schema_name, record.table_name
                ),
                column_id=generate_column_id(
                    record.database_name,
                    record.schema_name,
                    record.table_name,
                    record.column_name,
                ),
            )
            for record in records
        ]

    @staticmethod
    def _build_references_relationships(records: list[ReferenceRecord]) -> list[References]:
        """Build column→column foreign-key relationships from reference records.

        Skips self-referential rows (``source_column_id == target_column_id``), an
        ``INFORMATION_SCHEMA`` join artifact that is never a real foreign key.
        Only foreign-key rows reach the transform (the retriever filters and drops
        raw-name self-refs upstream); the id-level skip here also catches source
        and target names that differ only by case or separator.
        """
        relationships: list[References] = []
        for record in records:
            source_column_id = generate_column_id(
                record.source_database_name,
                record.source_schema_name,
                record.source_table_name,
                record.source_column_name,
            )
            target_column_id = generate_column_id(
                record.target_database_name,
                record.target_schema_name,
                record.target_table_name,
                record.target_column_name,
            )
            if source_column_id == target_column_id:
                continue
            relationships.append(
                References(
                    source_column_id=source_column_id,
                    target_column_id=target_column_id,
                    criteria=record.criteria,
                )
            )
        return relationships

    @staticmethod
    def _build_has_value_relationships(records: list[ValueRecord]) -> list[HasValue]:
        """Build column→value relationships, one per value record."""
        return [
            HasValue(
                column_id=generate_column_id(
                    record.database_name,
                    record.schema_name,
                    record.table_name,
                    record.column_name,
                ),
                value_id=generate_value_id(
                    record.database_name,
                    record.schema_name,
                    record.table_name,
                    record.column_name,
                    record.value,
                ),
            )
            for record in records
        ]
