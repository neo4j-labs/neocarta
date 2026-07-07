"""Unit tests for the MCP server settings.

Guards V-04: ``neo4j_password`` must be a ``SecretStr`` so accidental
serialisation (repr, str, model_dump_json) masks the value instead of leaking
the real Neo4j password — matching the CLI's existing discipline.
"""

import os

# ``neocarta._mcp.settings`` instantiates a ``Settings()`` singleton at import,
# and its Neo4j fields are required — make sure they are present regardless of
# whether a .env is discoverable in the test environment.
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "password")

from pydantic import SecretStr

from neocarta._mcp.settings import Settings

_SECRET = "s3cr3t-prod-password"  # noqa: S105 — test fixture, not a real credential


def _settings() -> Settings:
    return Settings(
        neo4j_uri="bolt://localhost:7687",
        neo4j_username="neo4j",
        neo4j_password=_SECRET,
    )


def test_neo4j_password_is_secretstr():
    settings = _settings()
    assert isinstance(settings.neo4j_password, SecretStr)


def test_get_secret_value_round_trips():
    settings = _settings()
    assert settings.neo4j_password.get_secret_value() == _SECRET


def test_repr_and_str_mask_the_password():
    settings = _settings()
    assert _SECRET not in repr(settings)
    assert _SECRET not in str(settings)
    assert str(settings.neo4j_password) == "**********"


def test_model_dump_json_masks_the_password():
    settings = _settings()
    dumped = settings.model_dump_json()
    assert _SECRET not in dumped
    assert "**********" in dumped
