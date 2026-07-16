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
