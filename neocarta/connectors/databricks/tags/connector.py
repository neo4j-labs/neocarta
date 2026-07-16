"""Databricks Unity Catalog governance-tags sub-connector."""

from __future__ import annotations

import logging
import warnings
from typing import TYPE_CHECKING

from ...._logging import log_transform_counts
from ....errors import ConfigError, StateError
from ....ingest.rdbms import Neo4jRDBMSLoader
from .extract import DatabricksTagsExtractor
from .transform import DatabricksTagsTransformer

if TYPE_CHECKING:
    from typing import Self

    from databricks.sdk import WorkspaceClient
    from neo4j import Driver

logger = logging.getLogger(__name__)

# (human label, transformer attribute) pairs logged at the end of transform().
_TRANSFORM_COUNTS = (
    ("governance tag keys", "governance_tag_key_nodes"),
    ("governance tag values", "governance_tag_value_nodes"),
)


class DatabricksTagsConnector:
    """
    Connector for Databricks Unity Catalog governed-tag *definitions*.

    Reads governed-tag definitions (tag policies) via the Databricks SDK
    (``WorkspaceClient.tag_policies``) — no SQL warehouse, no ``information_schema``
    — and maps them into the vendor-neutral governance-tag layer:

    - each governed tag *key* → a :GovernanceTagKey (carrying the tag's
      description — the agent-searchable surface);
    - each allowed *value* → a :GovernanceTagValue (name only — values have no
      description in Databricks, and none is synthesized);
    - each (key, value) pair → a ``HAS_VALUE_OPTION`` edge.

    Follows an Extract → Transform → Load pipeline; :meth:`ingest` runs all three
    stages and records the neocarta graph metadata node at the end.

    Tag *assignments* (object → tag → value) live in ``information_schema.*_tags``,
    which needs a SQL warehouse to read, so no ``TAGGED_WITH`` edges to
    :Column / :Table / :Schema (and no :GovernanceTag instance nodes) are produced
    here. That is the instance layer of the governance model and a planned
    follow-up.

    Parameters
    ----------
    workspace_client : databricks.sdk.WorkspaceClient
        An authenticated Databricks workspace client.
    neo4j_driver : Driver
        Neo4j driver instance.
    database_name : str, default "neo4j"
        Target Neo4j database name.
    source : str | None, default None
        Explicit namespace for the governance-tag node ids. When ``None`` it is
        derived from the workspace's metastore id (falling back to the host).
    system_prefixes : tuple[str, ...] | None, default None
        Tag-key prefixes treated as platform/system tags and excluded unless
        ``include_system_tags=True``. When ``None`` the connector's default set
        (``system.``/``class.``/``ai.``/``sap.``) is used; pass an empty tuple to
        disable prefix-based filtering.
    """

    def __init__(
        self,
        workspace_client: WorkspaceClient,
        neo4j_driver: Driver,
        database_name: str = "neo4j",
        *,
        source: str | None = None,
        system_prefixes: tuple[str, ...] | None = None,
    ) -> None:
        """Initialize the Databricks governance-tags connector."""
        if workspace_client is None:
            raise ConfigError(
                "workspace_client is required for the Databricks governance-tags connector.",
                suggestion="Pass workspace_client=WorkspaceClient(host=..., token=...).",
            )
        if neo4j_driver is None:
            raise ConfigError(
                "neo4j_driver is required for the Databricks governance-tags connector.",
                suggestion="Pass neo4j_driver=GraphDatabase.driver(...).",
            )
        self.workspace_client = workspace_client
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

        self.extractor = DatabricksTagsExtractor(
            workspace_client, source=source, system_prefixes=system_prefixes
        )
        self.transformer = DatabricksTagsTransformer()
        self.loader = Neo4jRDBMSLoader(neo4j_driver, database_name)
        self._extracted = False
        self._transformed = False

    def close(self) -> None:
        """No connector-owned resources to release; the injected client/driver are the caller's."""

    def __enter__(self) -> Self:
        """Return self for use as a context manager."""
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        """Release owned resources on context-manager exit."""
        self.close()

    def extract(self, *, include_system_tags: bool = False) -> None:
        """
        Extract governed-tag definitions into the cache.

        Parameters
        ----------
        include_system_tags : bool, default False
            Whether to include platform-managed governed tags — those whose key
            matches one of the connector's ``system_prefixes`` (default
            ``system.``/``class.``/``ai.``/``sap.``). These are auto-applied by
            the platform/partners rather than user-authored governance
            vocabulary, so they are excluded by default. This is a
            connector-specific choice about *which definitions to pull*, not a
            graph-entity-type filter, so it is a bespoke flag rather than an
            ``include_nodes`` value.
        """
        logger.info("Extracting Databricks governed-tag metadata...")
        self._extracted = False
        self._transformed = False
        self.extractor.extract(include_system_tags=include_system_tags)
        self._extracted = True

    def transform(self) -> None:
        """
        Transform cached governed-tag data into governance-tag nodes/edges.

        Raises:
        ------
        StateError
            If called before :meth:`extract`.
        """
        if not self._extracted:
            raise StateError(
                "DatabricksTagsConnector.transform() called before extract().",
                suggestion="Call connector.extract() before connector.transform().",
            )
        self._transformed = False
        logger.info("Transforming Databricks governed-tag metadata...")
        e = self.extractor
        t = self.transformer

        t.transform_to_governance_tag_key_nodes(e.tag_key_info)
        t.transform_value_layer(e.tag_value_info)
        log_transform_counts(logger, t, _TRANSFORM_COUNTS)
        self._transformed = True

    def load(self) -> None:
        """
        Load transformed governance-tag data into Neo4j.

        Raises:
        ------
        StateError
            If called before :meth:`transform`.
        """
        if not self._transformed:
            raise StateError(
                "DatabricksTagsConnector.load() called before transform(); call .transform() first.",
                suggestion="Call connector.extract() and connector.transform() first.",
            )
        t = self.transformer

        logger.info("Loading Databricks governed-tag metadata into Neo4j...")
        # properties_list omits undefined props: tag keys carry name + description;
        # allowed-value nodes carry only a name (Databricks values are bare), so
        # writing a description would set NULL.
        self.loader.load_governance_tag_key_nodes(
            t.governance_tag_key_nodes,
            properties_list=["name", "description"],
        )
        self.loader.load_governance_tag_value_nodes(
            t.governance_tag_value_nodes,
            properties_list=["name"],
        )
        self.loader.load_has_value_option_relationships(t.has_value_option_relationships)

    def ingest(self, *, include_system_tags: bool = False) -> None:
        """
        Run the Databricks governance-tags connector (extract → transform → load).

        Parameters
        ----------
        include_system_tags : bool, default False
            Whether to include platform-managed governed tags (those matching one
            of the connector's ``system_prefixes``).
        """
        self.extract(include_system_tags=include_system_tags)
        self.transform()
        self.load()
        self.loader.upsert_neocarta_graph_node()
        logger.info("Recorded neocarta graph metadata")
        logger.info("Databricks governance-tags connector completed successfully")

    def run(self, *, include_system_tags: bool = False) -> None:
        """
        Run the Databricks governance-tags connector.

        .. deprecated::
            Use :meth:`ingest` instead. ``run`` will be removed in a future release.
        """
        warnings.warn(
            "DatabricksTagsConnector.run() is deprecated; "
            "use DatabricksTagsConnector.ingest() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.ingest(include_system_tags=include_system_tags)
