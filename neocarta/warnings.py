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


class DatabricksGlossaryWarning(NeocartaWarning):
    """
    Emitted when the Databricks glossary connector falls back to a degraded mode.

    Currently raised when the connector cannot read the workspace's metastore id
    (e.g. no metastore assignment, or insufficient permissions) and therefore
    derives the synthesized ``Glossary`` node's id from the workspace host URL
    instead. Governed tags are account-level, so the host-derived id is
    workspace- rather than metastore-scoped; pass an explicit ``glossary_id`` to
    the connector to control it.

    Users can silence the warning category specifically::

        import warnings
        from neocarta.warnings import DatabricksGlossaryWarning

        warnings.filterwarnings("ignore", category=DatabricksGlossaryWarning)
    """
