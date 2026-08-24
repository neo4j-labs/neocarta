"""OSI (Open Semantic Interchange) connector — bidirectional Neo4j integration."""

from __future__ import annotations

import logging
import warnings
from typing import TYPE_CHECKING

from ..._logging import log_transform_counts
from ...errors import StateError
from ...warnings import UnsupportedOsiVersionWarning
from .export.extract import OsiGraphExtractor
from .export.transform import OsiExportTransformer
from .ingest.extract import OsiSpecExtractor
from .ingest.transform import OsiIngestTransformer
from .load import OsiNeo4jLoader

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Self

    from neo4j import Driver

logger = logging.getLogger(__name__)

# (human label, transformer attribute) pairs counted at the end of transform().
# OsiIngestTransformer exposes node lists as direct instance attributes rather
# than via transform_to_* methods, so counts are read off these after transform.
_OSI_COUNT_FIELDS = (
    ("semantic models", "osi_semantic_model_nodes"),
    ("databases", "database_nodes"),
    ("schemas", "schema_nodes"),
    ("tables", "table_nodes"),
    ("columns", "column_nodes"),
    ("queries", "query_nodes"),
    ("metrics", "metric_nodes"),
    ("joins", "join_nodes"),
    ("expressions", "expression_nodes"),
    ("AI contexts", "ai_context_nodes"),
    ("custom extensions", "custom_extension_nodes"),
    ("business terms", "business_term_nodes"),
)


class OsiConnector:
    """
    Bidirectional OSI connector.

    Supports two directions:

    - :meth:`ingest` reads an OSI YAML spec (local path or URL) and loads it into Neo4j.
    - :meth:`export` reads an OSI semantic model from Neo4j (filtered by name) and emits
      an OSI YAML spec.

    Ingest is decomposed into three public stages — :meth:`extract`, :meth:`transform`,
    :meth:`load` — that :meth:`ingest` runs in order. Export is exposed as a single
    public :meth:`export` orchestrator; its internal stages are not part of the
    public surface.

    Version handling
    ----------------
    The connector targets a known set of OSI spec versions (see
    :attr:`SUPPORTED_VERSIONS`). The ``version`` argument on :meth:`ingest` /
    :meth:`extract` declares which version the caller expects for that particular
    file; the connector emits a ``UserWarning`` if:

    - ``version`` is not in :attr:`SUPPORTED_VERSIONS` (the connector may miss
      features or behave unexpectedly), or
    - the parsed spec's ``version`` field is missing or does not match ``version``.

    ``version`` is purely an *ingest-time* compatibility check. :meth:`export`
    emits whatever ``osi_version`` was stored on the ``OsiSemanticModel`` node
    at ingest time — there is no export-side ``version`` argument.

    Parameters
    ----------
    neo4j_driver : neo4j.Driver
        Connected Neo4j driver.
    database_name : str, default "neo4j"
        Target Neo4j database.
    http_timeout : float, default 30.0
        Timeout in seconds when fetching an OSI spec by URL.
    """

    #: OSI spec versions the connector has been built against.
    SUPPORTED_VERSIONS: tuple[str, ...] = ("0.1.1",)

    def __init__(
        self,
        neo4j_driver: Driver,
        database_name: str = "neo4j",
        http_timeout: float = 30.0,
    ) -> None:
        """Initialize the OSI connector with a Neo4j driver and an OSI-aware loader."""
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name
        self.http_timeout = http_timeout
        self.loader = OsiNeo4jLoader(neo4j_driver, database_name)

        # Ingest-direction stages. Their caches are reset on each .extract() /
        # .transform() call so repeat ingests against the same instance behave
        # like independent runs.
        self.extractor = OsiSpecExtractor(http_timeout=http_timeout)
        self.transformer = OsiIngestTransformer()
        self._extracted = False
        self._transformed = False

    # ------------------------------------------------------------------ #
    # Ingest direction
    # ------------------------------------------------------------------ #

    def close(self) -> None:
        """No connector-owned resources to release; the injected Neo4j driver is the caller's."""

    def __enter__(self) -> Self:
        """Return self for use as a context manager."""
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        """Release owned resources on context-manager exit."""
        self.close()

    def extract(self, spec_source: str | Path, *, version: str = "0.1.1") -> None:
        """
        Read an OSI YAML spec into the connector's extract cache.

        Parameters
        ----------
        spec_source : str | Path
            A local filesystem path or an ``http(s)://`` URL pointing to the OSI YAML.
        version : str, default ``"0.1.1"``
            Declared OSI spec version. Emits a ``UserWarning`` if outside
            :attr:`SUPPORTED_VERSIONS` or if the parsed spec's ``version`` field
            is missing / doesn't match.
        """
        if version not in self.SUPPORTED_VERSIONS:
            warnings.warn(
                f"OSI version {version!r} is outside the supported set "
                f"{self.SUPPORTED_VERSIONS}; the connector may miss features "
                "or behave unexpectedly.",
                UnsupportedOsiVersionWarning,
                stacklevel=2,
            )

        logger.info("Extracting OSI spec from %s", spec_source)
        # Reset downstream lifecycle: any prior transform/load no longer
        # corresponds to the new source.
        self._extracted = False
        self._transformed = False
        self.extractor.extract(spec_source)
        self._check_spec_version(self.extractor.spec, version)
        self._extracted = True

    def transform(self) -> None:
        """
        Transform the cached OSI spec into graph data model objects.

        Raises:
        ------
        StateError
            If called before a successful :meth:`extract`.
        """
        if not self._extracted:
            raise StateError(
                "OsiConnector.transform() called before extract(); "
                "call .extract(spec_source) first.",
                suggestion="Call connector.extract(spec_source) before connector.transform().",
            )
        logger.info("Transforming OSI spec...")
        # OsiIngestTransformer accumulates state across .transform() calls; replace
        # the instance so repeat transforms behave like independent runs.
        self.transformer = OsiIngestTransformer()
        self.transformer.transform(self.extractor.spec)
        log_transform_counts(logger, self.transformer, _OSI_COUNT_FIELDS)
        self._transformed = True

    def load(self) -> None:
        """
        Load the most recent transform into Neo4j.

        Raises:
        ------
        StateError
            If called before a successful :meth:`transform`.
        """
        if not self._transformed:
            raise StateError(
                "OsiConnector.load() called before transform(); call .transform() first.",
                suggestion="Call connector.transform() before connector.load().",
            )
        logger.info("Loading OSI semantic model into Neo4j...")
        self._load_ingest(self.transformer)

    def ingest(self, spec_source: str | Path, *, version: str = "0.1.1") -> None:
        """
        Read an OSI YAML spec and load it into Neo4j (extract → transform → load).

        Parameters
        ----------
        spec_source : str | Path
            A local filesystem path or an ``http(s)://`` URL pointing to the OSI YAML.
        version : str, default ``"0.1.1"``
            Declared OSI spec version. See :meth:`extract` for warning behavior.
        """
        self.extract(spec_source, version=version)
        self.transform()
        self.load()
        self.loader.upsert_neocarta_graph_node()
        logger.info("Recorded neocarta graph metadata")
        logger.info("OSI ingest completed successfully")

    # ------------------------------------------------------------------ #
    # Export direction
    # ------------------------------------------------------------------ #

    def export(self, semantic_model_name: str, output_path: str | Path) -> None:
        """
        Read an OSI semantic model from Neo4j and emit an OSI YAML spec.

        Parameters
        ----------
        semantic_model_name : str
            The ``name`` of the :OsiSemanticModel to export. Required.
        output_path : str | Path
            Destination path for the OSI YAML output.
        """
        logger.info("Extracting OSI semantic model '%s' from Neo4j...", semantic_model_name)
        graph_extractor = OsiGraphExtractor(self.neo4j_driver, self.database_name)
        snapshot = graph_extractor.extract(semantic_model_name)

        logger.info("Transforming graph snapshot to OSI spec...")
        graph_transformer = OsiExportTransformer()
        graph_transformer.transform(snapshot)

        logger.info("Writing OSI YAML to %s", output_path)
        graph_transformer._to_yaml(output_path)
        logger.info("OSI export completed successfully")

    # ------------------------------------------------------------------ #
    # Deprecated entrypoint
    # ------------------------------------------------------------------ #

    def run(self, spec_source: str | Path) -> None:
        """
        Run the OSI connector in ingest mode.

        .. deprecated::
            Use :meth:`ingest` instead. ``run`` will be removed in a future release.
        """
        warnings.warn(
            "OsiConnector.run() is deprecated; use OsiConnector.ingest() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.ingest(spec_source)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _check_spec_version(self, spec: dict | None, expected_version: str) -> None:
        """
        Warn (don't raise) when the parsed spec's ``version`` doesn't match
        ``expected_version`` or is missing entirely. Compatibility is best-effort —
        the ingest proceeds either way.
        """
        if spec is None:
            return
        spec_version = spec.get("version")
        if spec_version is None:
            warnings.warn(
                "OSI YAML has no top-level `version` field; can't verify "
                f"compatibility with expected version {expected_version!r}.",
                UnsupportedOsiVersionWarning,
                stacklevel=3,
            )
            return
        if str(spec_version) != expected_version:
            warnings.warn(
                f"OSI YAML declares version {str(spec_version)!r} but ingest was "
                f"called with version {expected_version!r}; ingest may be lossy "
                "or miss features.",
                UnsupportedOsiVersionWarning,
                stacklevel=3,
            )

    def _load_ingest(self, transformer: OsiIngestTransformer) -> None:
        """Load all nodes and relationships produced by an ingest transformer.

        Order matters for referential integrity in Neo4j: parent nodes are loaded
        before their children, and relationships only after both endpoints exist.
        """
        loader = self.loader

        # Each OSI-specific node loader MERGEs on the primary label (e.g. :Table)
        # and adds the OSI subtype label (e.g. :OsiTable) in the same write, so we
        # don't also call the base loader's load_table_nodes — that would create
        # the node first and the second call's ON CREATE props (source,
        # primary_key, unique_keys) would never fire.
        if transformer.database_nodes:
            loader.load_database_nodes(transformer.database_nodes)
        if transformer.schema_nodes:
            loader.load_schema_nodes(transformer.schema_nodes)
        if transformer.table_nodes:
            loader.load_osi_table_nodes(transformer.table_nodes)
        if transformer.column_nodes:
            loader.load_osi_column_nodes(transformer.column_nodes)
        if transformer.query_nodes:
            loader.load_query_nodes(
                transformer.query_nodes,
                properties_list=["name", "content", "description"],
            )
        if transformer.osi_semantic_model_nodes:
            loader.load_osi_semantic_model_nodes(transformer.osi_semantic_model_nodes)
        if transformer.metric_nodes:
            loader.load_metric_nodes(transformer.metric_nodes)
        if transformer.join_nodes:
            loader.load_join_nodes(transformer.join_nodes)
        if transformer.expression_nodes:
            loader.load_expression_nodes(transformer.expression_nodes)
        if transformer.ai_context_nodes:
            loader.load_osi_ai_context_nodes(transformer.ai_context_nodes)
        if transformer.custom_extension_nodes:
            loader.load_osi_custom_extensions_nodes(transformer.custom_extension_nodes)
        if transformer.business_term_nodes:
            loader.load_business_term_nodes_by_name(transformer.business_term_nodes)

        # Relationships
        if transformer.has_schema_rels:
            loader.load_has_schema_relationships(transformer.has_schema_rels)
        if transformer.has_table_rels:
            loader.load_has_table_relationships(transformer.has_table_rels)
        if transformer.has_column_rels:
            loader.load_has_column_relationships(transformer.has_column_rels)
        if transformer.references_rels:
            loader.load_references_relationships(transformer.references_rels)
        if transformer.domain_has_table_rels:
            loader.load_domain_has_table_relationships(transformer.domain_has_table_rels)
        if transformer.has_query_rels:
            loader.load_has_query_relationships(transformer.has_query_rels)
        if transformer.uses_column_rels:
            loader.load_uses_column_relationships(transformer.uses_column_rels)
        if transformer.has_metric_rels:
            loader.load_has_metric_relationships(transformer.has_metric_rels)
        if transformer.metric_uses_table_rels:
            loader.load_metric_uses_table_relationships(transformer.metric_uses_table_rels)
        if transformer.metric_uses_column_rels:
            loader.load_metric_uses_column_relationships(transformer.metric_uses_column_rels)
        if transformer.has_aspect_rels:
            loader.load_has_aspect_relationships(transformer.has_aspect_rels)
        if transformer.has_expression_rels:
            loader.load_has_expression_relationships(transformer.has_expression_rels)
        if transformer.has_source_table_rels:
            loader.load_has_source_table_relationships(transformer.has_source_table_rels)
        if transformer.has_target_table_rels:
            loader.load_has_target_table_relationships(transformer.has_target_table_rels)
        if transformer.used_in_join_rels:
            loader.load_used_in_join_relationships(transformer.used_in_join_rels)
        if transformer.tagged_with_rels:
            loader.load_osi_tagged_with_relationships(
                transformer.tagged_with_rels,
                transformer.business_term_nodes,
            )
