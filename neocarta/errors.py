"""Library-wide exception hierarchy for Neocarta.

All exceptions raised intentionally by the library inherit from
:class:`NeocartaError`. Each carries structured context the CLI adapter
(see :mod:`neocarta._cli.errors`) can map to a documented exit-code envelope.

The class-level ``code`` attribute on each subclass must match an entry in
``neocarta._cli.errors.EXIT_CODES``.
"""

from __future__ import annotations

from typing import Any


class NeocartaError(Exception):
    """Base class for all Neocarta library errors.

    Parameters
    ----------
    message : str
        Single-line human-readable summary.
    suggestion : str, optional
        Concrete next step the user can take.
    retryable : bool
        Whether the operation is safe to retry as-is.
    details : dict, optional
        Structured context (connector name, node label, query snippet, ...).
    """

    code: str = "general_failure"

    def __init__(
        self,
        message: str,
        *,
        suggestion: str | None = None,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialise the error with a message and optional structured context."""
        super().__init__(message)
        self.message = message
        self.suggestion = suggestion
        self.retryable = retryable
        self.details: dict[str, Any] = details or {}


# --- Configuration / auth (apply to any stage) -----------------------------


class ConfigError(NeocartaError):
    """Required configuration is missing, malformed, or semantically invalid.

    Use for bad constructor arguments, missing identifiers, unknown
    properties on a model, etc. Replaces ad-hoc :class:`ValueError` raises
    across connectors and ingest.
    """

    code = "validation_error"


class AuthError(NeocartaError):
    """Credentials are missing, invalid, or refused by an upstream service."""

    code = "auth_error"


class StateError(NeocartaError):
    """A method was called when the object is not in a valid state for it.

    Use for call-ordering or sequencing problems — e.g. a downstream
    extractor method invoked before its required prerequisite. Distinct
    from :class:`ConfigError`: the arguments are fine, but the receiver
    is not yet ready.
    """

    code = "validation_error"


# --- Cross-cutting ----------------------------------------------------------


class RateLimitError(NeocartaError):
    """Upstream service rate-limited or quota-exceeded the request."""

    code = "rate_limited"

    def __init__(self, message: str, **kwargs: Any) -> None:
        """Default ``retryable=True`` since backoff-and-retry is the usual response."""
        kwargs.setdefault("retryable", True)
        super().__init__(message, **kwargs)


class OperationTimeoutError(NeocartaError):
    """A Neocarta operation exceeded its time budget."""

    code = "timeout"

    def __init__(self, message: str, **kwargs: Any) -> None:
        """Default ``retryable=True`` since a longer budget often succeeds."""
        kwargs.setdefault("retryable", True)
        super().__init__(message, **kwargs)


# --- Source-side pipeline ---------------------------------------------------


class ConnectorError(NeocartaError):
    """Connector client could not be initialized or reached."""

    code = "upstream_error"


class ExtractionError(NeocartaError):
    """An extraction query against a source system failed."""

    code = "upstream_error"


class TransformError(NeocartaError):
    """Extracted data could not be coerced into the Pydantic data model.

    Distinct from :class:`ConfigError`: this means the source returned a
    shape that was not expected, not that the caller passed bad input.
    """

    code = "validation_error"


class EnrichmentError(NeocartaError):
    """Embedding generation or other enrichment step failed."""

    code = "upstream_error"


# --- Neo4j / ingest side ----------------------------------------------------


class Neo4jError(NeocartaError):
    """Base for any failure interacting with Neo4j."""

    code = "upstream_error"


class Neo4jConnectionError(Neo4jError):
    """Cannot reach the Neo4j instance (driver init, routing, network)."""


class LoadError(Neo4jError):
    """A node or relationship write to Neo4j failed."""


class ConstraintCreationError(Neo4jError):
    """Creating a uniqueness or node-key constraint failed.

    Separate from :class:`LoadError` because constraint setup typically
    fails on permissions or edition mismatch (e.g. NODE KEY on Community
    Edition), not on row data.
    """


class IndexCreationError(Neo4jError):
    """Creating a vector or full-text index failed.

    Separate from :class:`LoadError` for the same reason as
    :class:`ConstraintCreationError`: index creation is setup, not data load.
    """
