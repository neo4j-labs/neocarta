"""Unit tests for the core dbxcarta CLI (verify/preset path)."""

from __future__ import annotations

import pytest
from dbxcarta.spark import cli


class _Secret:
    def __init__(self, value: str | None) -> None:
        self.value = value


class _Secrets:
    def __init__(self, values: dict[str, str | None]) -> None:
        self._values = values

    def get_secret(self, *, scope: str, key: str) -> _Secret:
        return _Secret(self._values.get(key))


class _Ws:
    def __init__(self, values: dict[str, str | None]) -> None:
        self.secrets = _Secrets(values)


class _Settings:
    databricks_secret_scope = "dbxcarta"


def test_build_neo4j_driver_raises_on_missing_secret() -> None:
    # NEO4J_URI is resolved first; a None value must surface as an explicit
    # error naming the key and scope, not an opaque b64decode TypeError.
    ws = _Ws({"NEO4J_URI": None})

    with pytest.raises(RuntimeError, match="'NEO4J_URI'.*'dbxcarta'"):
        cli._build_neo4j_driver(ws, _Settings())  # type: ignore[arg-type]
