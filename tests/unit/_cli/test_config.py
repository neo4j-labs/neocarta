"""Regression tests for CLI settings — secrets must remain wrapped.

These tests pin down the behaviour that addresses CodeQL alert #6
(``py/clear-text-logging-sensitive-data``) on PR #139: passwords and API keys
must be typed as :class:`pydantic.SecretStr` so that accidental
:func:`json.dumps`, :func:`repr`, or :func:`str` calls cannot leak the raw
value.
"""

import json

import pytest
from pydantic import SecretStr

from neocarta._cli.config import CLISettings, require_secret
from neocarta._cli.errors import CLIError


def test_neo4j_password_is_secret_str(monkeypatch):
    monkeypatch.setenv("NEO4J_PASSWORD", "super-secret-value")
    settings = CLISettings()
    assert isinstance(settings.neo4j_password, SecretStr)
    assert settings.neo4j_password.get_secret_value() == "super-secret-value"


def test_secret_does_not_leak_through_str_or_repr(monkeypatch):
    monkeypatch.setenv("NEO4J_PASSWORD", "super-secret-value")
    settings = CLISettings()
    assert "super-secret-value" not in str(settings.neo4j_password)
    assert "super-secret-value" not in repr(settings.neo4j_password)
    assert "super-secret-value" not in repr(settings)


def test_secret_does_not_leak_through_json_dumps(monkeypatch):
    monkeypatch.setenv("NEO4J_PASSWORD", "super-secret-value")
    settings = CLISettings()
    # ``default=str`` is the exact path used by ``emit_json`` in output.py.
    # It must NOT round-trip the raw secret value.
    serialized = json.dumps(settings.model_dump(), default=str)
    assert "super-secret-value" not in serialized


def test_require_secret_raises_on_missing():
    with pytest.raises(CLIError) as excinfo:
        require_secret("NEO4J_PASSWORD", None, env_var="NEO4J_PASSWORD")
    assert excinfo.value.code == "usage_error"
    assert "NEO4J_PASSWORD" in excinfo.value.message


def test_require_secret_raises_on_empty():
    with pytest.raises(CLIError) as excinfo:
        require_secret("NEO4J_PASSWORD", SecretStr(""), env_var="NEO4J_PASSWORD")
    assert excinfo.value.code == "usage_error"


def test_require_secret_returns_value_when_set():
    secret = SecretStr("populated")
    assert require_secret("NEO4J_PASSWORD", secret, env_var="NEO4J_PASSWORD") is secret


def test_embedding_env_vars_are_read(monkeypatch):
    # #187: all three EMBEDDING_* vars must be read from the environment via the
    # explicit validation_alias on each field.
    monkeypatch.setenv("EMBEDDING_MODEL", "gemini-embedding-001")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "256")
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "32")
    settings = CLISettings()
    assert settings.embedding_model == "gemini-embedding-001"
    assert settings.embedding_dimensions == 256
    assert settings.embedding_batch_size == 32


def test_embedding_defaults_when_env_absent(monkeypatch):
    for var in ("EMBEDDING_MODEL", "EMBEDDING_DIMENSIONS", "EMBEDDING_BATCH_SIZE"):
        monkeypatch.delenv(var, raising=False)
    settings = CLISettings()
    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.embedding_dimensions is None
    assert settings.embedding_batch_size == 100
