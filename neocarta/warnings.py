"""Library-wide warning hierarchy for Neocarta.

All non-fatal compatibility / soft-error signals raised by the library go
through subclasses of :class:`NeocartaWarning` so callers can filter them
specifically::

    import warnings
    from neocarta.warnings import NeocartaWarning

    warnings.filterwarnings("ignore", category=NeocartaWarning)

Sibling of :mod:`neocarta.errors`. Errors are raised; warnings are emitted.
"""

from __future__ import annotations


class NeocartaWarning(UserWarning):
    """Base class for all Neocarta library warnings.

    Subclasses :class:`UserWarning` so existing user-facing warning filters
    still catch Neocarta warnings, while allowing callers to silence specific
    Neocarta warning categories without hiding unrelated ``UserWarning``s.
    """


class UnsupportedOsiVersionWarning(NeocartaWarning):
    """
    Emitted when the OSI connector encounters a spec version it wasn't built for.

    Covers three cases:

    - The ``version`` passed to ``OsiConnector.ingest`` is not in
      ``OsiConnector.SUPPORTED_VERSIONS``.
    - The parsed OSI YAML's top-level ``version`` field is missing entirely.
    - The parsed spec's ``version`` doesn't match the declared ingest version.

    Users can silence the warning category specifically::

        import warnings
        from neocarta.warnings import UnsupportedOsiVersionWarning

        warnings.filterwarnings("ignore", category=UnsupportedOsiVersionWarning)
    """


class DatabricksTagsWarning(NeocartaWarning):
    """
    Emitted by the Databricks governance-tags connector for non-fatal soft errors.

    Currently raised when the workspace's metastore id cannot be read, so the
    governance-tag id namespace falls back to the workspace host (which is
    workspace-scoped, while governed tags are account-level). Pass ``source=...``
    to set the namespace explicitly and silence it.

    Users can silence the warning category specifically::

        import warnings
        from neocarta.warnings import DatabricksTagsWarning

        warnings.filterwarnings("ignore", category=DatabricksTagsWarning)
    """


class Neo4jSchemaWarning(NeocartaWarning):
    """
    Emitted by the Neo4j connector for non-fatal degraded reads.

    Raised when the source graph's schema can be read but some detail is
    unavailable or degraded, for example:

    - The source is Community Edition, which has no property-existence constraints,
      so ``Property.existence`` is ``False`` and ``nullable`` defaults to ``True``.
    - ``apoc.meta.schema()`` returns a partial or unexpected shape for a label, so
      that portion is skipped rather than failing the whole run.
    - The introspected source database has no node labels (an empty schema); only
      ``Database`` / ``Schema`` are written.

    Users can silence the warning category specifically::

        import warnings
        from neocarta.warnings import Neo4jSchemaWarning

        warnings.filterwarnings("ignore", category=Neo4jSchemaWarning)
    """
