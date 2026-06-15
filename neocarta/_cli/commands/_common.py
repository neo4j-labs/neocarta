"""Shared Neo4j and embedder helpers for the CLI connector commands.

Factored out of the individual command modules (``bigquery``, ``csv``) so the
Neo4j driver lifecycle, credential validation, and embedder construction live in
one place and stay consistent across connectors. The secret-handling discipline
— never binding a raw secret to a named local variable — is preserved here.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from ...enums import NodeLabel
from ..config import require, require_secret

if TYPE_CHECKING:
    from collections.abc import Iterator

    from neo4j import Driver

    from ...enrichment.embeddings import BaseEmbeddingsConnector, LiteLLMEmbeddingsConnector
    from ..config import CLISettings


DEFAULT_SCHEMA_NODE_LABELS = (
    NodeLabel.DATABASE,
    NodeLabel.SCHEMA,
    NodeLabel.TABLE,
    NodeLabel.COLUMN,
)


def _require_neo4j_settings(settings: CLISettings) -> None:
    """Validate that Neo4j credentials are configured.

    Returns nothing on purpose: callers must read non-secret fields off the
    settings object directly, and the secret password is only unwrapped inside
    :func:`_neo4j_driver` at the point of use. This keeps the raw password
    out of named local variables and out of CodeQL's reach as a logging-sink
    source.
    """
    require("NEO4J_URI", settings.neo4j_uri, env_var="NEO4J_URI")
    require("NEO4J_USERNAME", settings.neo4j_username, env_var="NEO4J_USERNAME")
    require_secret(
        "NEO4J_PASSWORD",
        settings.neo4j_password,
        env_var="NEO4J_PASSWORD",
    )


@contextlib.contextmanager
def _neo4j_driver(settings: CLISettings) -> Iterator[Driver]:
    """Yield a Neo4j driver for ``settings`` and close it on exit.

    The password is unwrapped inline via ``settings.neo4j_password
    .get_secret_value()`` so the raw secret string is never bound to a named
    local variable in the caller's scope.
    """
    # Lazy import: keeps `neocarta --help` and `agent-context` fast and lets
    # tests run without a Neo4j driver installed.
    from neo4j import GraphDatabase  # noqa: PLC0415

    # _require_neo4j_settings has already raised CLIError if any of these are
    # missing; the asserts narrow the type for the GraphDatabase.driver call.
    assert settings.neo4j_uri is not None  # noqa: S101
    assert settings.neo4j_password is not None  # noqa: S101
    driver = GraphDatabase.driver(
        uri=settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password.get_secret_value()),
    )
    try:
        yield driver
    finally:
        driver.close()


def _build_embedder(
    settings: CLISettings,
    neo4j_driver: Driver,
) -> LiteLLMEmbeddingsConnector:
    """Construct a LiteLLMEmbeddingsConnector for post-load embedding runs.

    LiteLLM routes to the provider implied by ``embedding_model`` and reads
    provider auth (``OPENAI_API_KEY``, ``GEMINI_API_KEY``, ...) directly from
    the environment, so no secret is unwrapped here. The vector dimension is
    auto-detected from the model on first use; when ``embedding_dimensions`` is
    set (via ``--embedding-dimensions``) it is forwarded to LiteLLM for models
    that support dimension truncation.
    """
    # Lazy import: the embedding stack is only loaded when embeddings run.
    from ...enrichment.embeddings import LiteLLMEmbeddingsConnector  # noqa: PLC0415

    return LiteLLMEmbeddingsConnector(
        neo4j_driver=neo4j_driver,
        embedding_model=settings.embedding_model,
        database_name=settings.neo4j_database,
        dimensions=settings.embedding_dimensions,
    )


def _run_embeddings(
    embedder: BaseEmbeddingsConnector,
    node_labels: list[NodeLabel],
    batch_size: int = 100,
) -> None:
    """Run an embedder and normalise failures into the CLI error contract.

    Library-level :class:`NeocartaError` instances (e.g. a Neo4j
    ``IndexCreationError``) are re-raised unchanged so the caller's
    ``cli_error_from`` adapter maps them to their declared exit code. Any other
    failure — LiteLLM surfaces missing/invalid credentials or an unknown model
    as a plain ``RuntimeError`` from the dimension probe — is wrapped in a
    structured :class:`CLIError` so agents get a clean envelope instead of a
    raw traceback.

    ``batch_size`` is the number of nodes embedded per provider request,
    resolved from ``--embedding-batch-size`` / ``EMBEDDING_BATCH_SIZE``.
    """
    # Local imports keep the error deps off the --help / --dry-run path.
    from ...errors import NeocartaError  # noqa: PLC0415
    from ..errors import CLIError  # noqa: PLC0415

    try:
        embedder.run(node_labels=node_labels, batch_size=batch_size)
    except NeocartaError:
        raise
    except Exception as exc:  # provider/probe failures aren't NeocartaError
        raise CLIError(
            "upstream_error",
            "Embedding generation failed.",
            suggestion=(
                "Check the embedding provider credentials and that the model id "
                "is valid for your provider (e.g. set OPENAI_API_KEY for OpenAI "
                "models, GEMINI_API_KEY for Gemini)."
            ),
        ) from exc
