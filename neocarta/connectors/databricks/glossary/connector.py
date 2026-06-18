"""Databricks governed-tags glossary sub-connector."""

from __future__ import annotations

import logging
import warnings
from typing import TYPE_CHECKING

from ...._logging import log_transform_counts
from ....errors import ConfigError, StateError
from ....ingest.rdbms import Neo4jRDBMSLoader
from .extract import DatabricksGlossaryExtractor
from .transform import DatabricksGlossaryTransformer

if TYPE_CHECKING:
    from typing import Self

    from databricks.sdk import WorkspaceClient
    from neo4j import Driver

logger = logging.getLogger(__name__)

# (human label, transformer attribute) pairs logged at the end of transform().
_TRANSFORM_COUNTS = (
    ("glossaries", "glossary_nodes"),
    ("categories", "category_nodes"),
    ("business terms", "business_term_nodes"),
)


class DatabricksGlossaryConnector:
    """
    Connector for Databricks Unity Catalog governed-tag *definitions*.

    Reads governed-tag definitions (tag policies) via the Databricks SDK
    (``WorkspaceClient.tag_policies``) — no SQL warehouse, no ``information_schema``
    — and maps them into the business-glossary layer:

    - one synthesized account/metastore-level :Glossary node;
    - each governed tag *key* → a :Category (carrying the tag's description);
    - each allowed *value* → a :BusinessTerm (name only — values have no
      description in Databricks, and none is synthesized).

    Follows an Extract → Transform → Load pipeline; :meth:`ingest` runs all three
    stages and records the neocarta graph metadata node at the end.

    Tag *assignments* (object → tag → value) are not read in v1, so no
    ``TAGGED_WITH`` edges to :Column / :Table / :Schema are produced. That is a
    planned follow-up gated behind an ``include_assignments`` flag.

    Parameters
    ----------
    workspace_client : databricks.sdk.WorkspaceClient
        An authenticated Databricks workspace client.
    neo4j_driver : Driver
        Neo4j driver instance.
    database_name : str, default "neo4j"
        Target Neo4j database name.
    glossary_id : str | None, default None
        Explicit id for the synthesized :Glossary node. When ``None`` it is
        derived from the workspace's metastore id (falling back to the host).
    glossary_name : str, default "Unity Catalog Governed Tags"
        Display name for the synthesized :Glossary node.
    """

    def __init__(
        self,
        workspace_client: WorkspaceClient,
        neo4j_driver: Driver,
        database_name: str = "neo4j",
        *,
        glossary_id: str | None = None,
        glossary_name: str = "Unity Catalog Governed Tags",
    ) -> None:
        """Initialize the Databricks glossary connector."""
        if workspace_client is None:
            raise ConfigError(
                "workspace_client is required for the Databricks glossary connector.",
                suggestion="Pass workspace_client=WorkspaceClient(host=..., token=...).",
            )
        self.workspace_client = workspace_client
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

        self.extractor = DatabricksGlossaryExtractor(
            workspace_client,
            glossary_id=glossary_id,
            glossary_name=glossary_name,
        )
        self.transformer = DatabricksGlossaryTransformer()
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
            Whether to include platform-managed ``system.*`` governed tags
            (e.g. ``system.certification_status``). These are not user-authored
            business vocabulary, so they are excluded by default. This is a
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
        Transform cached governed-tag data into glossary nodes/edges.

        Raises:
        ------
        StateError
            If called before :meth:`extract`.
        """
        if not self._extracted:
            raise StateError(
                "DatabricksGlossaryConnector.transform() called before extract().",
                suggestion="Call connector.extract() before connector.transform().",
            )
        self._transformed = False
        logger.info("Transforming Databricks governed-tag metadata...")
        e = self.extractor
        t = self.transformer

        t.transform_to_glossary_nodes(e.glossary_info)
        t.transform_to_category_nodes(e.category_info)
        t.transform_to_business_term_nodes(e.business_term_info)

        t.transform_to_has_category_relationships(e.category_info)
        t.transform_to_has_business_term_relationships(e.business_term_info)
        log_transform_counts(logger, t, _TRANSFORM_COUNTS)
        self._transformed = True

    def load(self) -> None:
        """
        Load transformed glossary data into Neo4j.

        Raises:
        ------
        StateError
            If called before :meth:`transform`.
        """
        if not self._transformed:
            raise StateError(
                "DatabricksGlossaryConnector.load() called before transform(); "
                "call .transform() first.",
                suggestion="Call connector.extract() and connector.transform() first.",
            )
        t = self.transformer

        logger.info("Loading Databricks governed-tag metadata into Neo4j...")
        # properties_list omits undefined props: Categories carry the tag key's
        # description + the tag policy id; allowed-value BusinessTerms carry
        # neither (name only), so writing description/resource_path would set NULL.
        self.loader.load_glossary_nodes(
            t.glossary_nodes,
            properties_list=["name", "resource_path"],
        )
        self.loader.load_category_nodes(
            t.category_nodes,
            properties_list=["name", "description", "resource_path"],
        )
        self.loader.load_business_term_nodes(
            t.business_term_nodes,
            properties_list=["name"],
        )

        self.loader.load_has_category_relationships(t.has_category_relationships)
        self.loader.load_has_business_term_relationships(t.has_business_term_relationships)

    def ingest(self, *, include_system_tags: bool = False) -> None:
        """
        Run the Databricks glossary connector (extract → transform → load).

        Parameters
        ----------
        include_system_tags : bool, default False
            Whether to include platform-managed ``system.*`` governed tags.
        """
        self.extract(include_system_tags=include_system_tags)
        self.transform()
        self.load()
        self.loader.upsert_neocarta_graph_node()
        logger.info("Recorded neocarta graph metadata")
        logger.info("Databricks glossary connector completed successfully")

    def run(self, *, include_system_tags: bool = False) -> None:
        """
        Run the Databricks glossary connector.

        .. deprecated::
            Use :meth:`ingest` instead. ``run`` will be removed in a future release.
        """
        warnings.warn(
            "DatabricksGlossaryConnector.run() is deprecated; "
            "use DatabricksGlossaryConnector.ingest() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.ingest(include_system_tags=include_system_tags)
