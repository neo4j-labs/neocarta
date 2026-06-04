"""Unit tests for read_workspace_secret (shared base64 secret decode)."""

from __future__ import annotations

import base64

import pytest
from dbxcarta.core.workspace import read_workspace_secret


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


def test_read_workspace_secret_base64_decodes_value() -> None:
    encoded = base64.b64encode(b"neo4j+s://host:7687").decode()
    ws = _Ws({"NEO4J_URI": encoded})

    assert (
        read_workspace_secret(ws, "dbxcarta", "NEO4J_URI")  # type: ignore[arg-type]
        == "neo4j+s://host:7687"
    )


def test_read_workspace_secret_raises_on_missing_secret() -> None:
    ws = _Ws({"NEO4J_URI": None})

    with pytest.raises(RuntimeError, match="'NEO4J_URI'.*'dbxcarta'"):
        read_workspace_secret(ws, "dbxcarta", "NEO4J_URI")  # type: ignore[arg-type]
