"""Neo4jSchema extractor."""

from ...._logging import log_stage


class Neo4jSchemaExtractor:
    """Extractor for neo4jschema metadata.

    Internal cached state is *not* part of the public API — callers interact
    only through the connector's stage methods. Expose extract results as
    read-only properties that :class:`Neo4jSchemaTransformer` consumes.
    """

    def __init__(self) -> None:
        """Initialize an empty extractor cache."""
        self._cache: dict = {}

    @log_stage
    def extract(self, source: str | None = None) -> None:
        """Read from the source and populate ``self._cache``.

        ``@log_stage`` logs a one-line INFO summary (target + row count +
        elapsed) for this call; it derives its logger from this module, never
        logs SQL or row values, and surfaces only allowlisted scalar kwargs as
        the target. TODO: replace this stub with concrete ``extract_*_info(...)``
        methods — decorate each with ``@log_stage`` — that populate
        ``self._cache``, plus ``@property`` accessors (``table_info``,
        ``column_info``, ...) for the transformer to read.
        """
        raise NotImplementedError(f"{type(self).__name__}.extract() not implemented for {source!r}")
