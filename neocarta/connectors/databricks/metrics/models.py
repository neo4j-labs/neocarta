"""Models for Databricks Unity Catalog metric-view extraction."""

from typing import Any, TypedDict


class MetricViewInfo(TypedDict):
    """One discovered Unity Catalog metric view and its parsed YAML definition.

    A metric view's definition is YAML (the object is created via
    ``CREATE VIEW … AS $$<yaml>$$``), so the extractor reads the view text and
    parses it; ``definition`` is the parsed mapping that
    :class:`~neocarta.connectors.databricks.metrics.transform.DatabricksMetricsTransformer`
    consumes.
    """

    full_name: str
    """The original-cased three-part name ``catalog.schema.name`` — preserved as
    the OSI semantic-model name and the ``OsiTable.source`` lineage pointer."""
    catalog: str
    schema: str
    name: str
    comment: str | None
    """The Unity Catalog object comment, used as a description fallback when the
    metric-view YAML carries no top-level ``comment``."""
    definition: dict[str, Any]
    """The parsed metric-view YAML mapping (``version`` / ``source`` / ``fields``
    or ``dimensions`` / ``measures`` / …)."""
