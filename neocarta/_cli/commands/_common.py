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

    from ...enrichment.embeddings import OpenAIEmbeddingsConnector
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
) -> OpenAIEmbeddingsConnector:
    """Construct an OpenAIEmbeddingsConnector for post-load embedding runs.

    The OpenAI API key is unwrapped from :class:`SecretStr` inline in the
    ``OpenAI(...)`` constructor call, so the raw key is never assigned to a
    named local variable.
    """
    # Lazy import: heavy dependencies are only loaded when embeddings run.
    from openai import OpenAI  # noqa: PLC0415

    from ...enrichment.embeddings import OpenAIEmbeddingsConnector  # noqa: PLC0415

    require_secret(
        "OPENAI_API_KEY",
        settings.openai_api_key,
        env_var="OPENAI_API_KEY",
    )
    # require_secret raised on missing/empty; the assert narrows the type.
    assert settings.openai_api_key is not None  # noqa: S101
    return OpenAIEmbeddingsConnector(
        neo4j_driver=neo4j_driver,
        client=OpenAI(api_key=settings.openai_api_key.get_secret_value()),
        embedding_model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        database_name=settings.neo4j_database,
    )
