"""Transform neo4jschema data into graph nodes and relationships."""

from ....connectors.models import NodesCache, RelationshipsCache

# All node ids MUST be produced via helpers in
# neocarta.connectors.utils.generate_id — never inline an id f-string.


class Neo4jSchemaTransformer:
    """Transformer for neo4jschema metadata."""

    def __init__(self) -> None:
        """Initialize the neo4jschema transformer."""
        self._node_cache: NodesCache = NodesCache()
        self._relationships_cache: RelationshipsCache = RelationshipsCache()

    # TODO: add transform_to_*_nodes / transform_to_*_relationships methods
    # that read the extractor caches and build data_model objects, plus
    # @property accessors (table_nodes, ...) for the loader to read.
