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


def test_openai_api_key_is_secret_str(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-a-real-key")
    settings = CLISettings()
    assert isinstance(settings.openai_api_key, SecretStr)
    assert settings.openai_api_key.get_secret_value() == "sk-not-a-real-key"


def test_secret_does_not_leak_through_str_or_repr(monkeypatch):
    monkeypatch.setenv("NEO4J_PASSWORD", "super-secret-value")
    settings = CLISettings()
    assert "super-secret-value" not in str(settings.neo4j_password)
    assert "super-secret-value" not in repr(settings.neo4j_password)
    assert "super-secret-value" not in repr(settings)


def test_secret_does_not_leak_through_json_dumps(monkeypatch):
    monkeypatch.setenv("NEO4J_PASSWORD", "super-secret-value")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-a-real-key")
    settings = CLISettings()
    # ``default=str`` is the exact path used by ``emit_json`` in output.py.
    # It must NOT round-trip the raw secret value.
    serialized = json.dumps(settings.model_dump(), default=str)
    assert "super-secret-value" not in serialized
    assert "sk-not-a-real-key" not in serialized


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
