from __future__ import annotations

import pytest
from dbxcarta.client.local_generation import (
    LocalGenerationError,
    extract_generated_text,
    generate_sql_local,
)


def test_extract_generated_text_openai_chat_shape() -> None:
    data = {
        "choices": [
            {
                "message": {
                    "content": "SELECT COUNT(*) FROM accounts",
                }
            }
        ]
    }

    assert extract_generated_text(data) == "SELECT COUNT(*) FROM accounts"


def test_extract_generated_text_predictions_shape() -> None:
    data = {"predictions": [{"text": "SELECT 1"}]}

    assert extract_generated_text(data) == "SELECT 1"


def test_extract_generated_text_responses_output_shape() -> None:
    data = {
        "output": [
            {
                "content": [
                    {"type": "output_text", "text": "SELECT "},
                    {"type": "output_text", "text": "1"},
                ]
            }
        ]
    }

    assert extract_generated_text(data) == "SELECT 1"


def test_extract_generated_text_raises_on_error() -> None:
    with pytest.raises(LocalGenerationError, match="bad endpoint"):
        extract_generated_text({"error": "bad endpoint"})


def test_generate_sql_local_posts_chat_payload(monkeypatch) -> None:
    calls = {}

    class FakeConfig:
        host = "https://example.cloud.databricks.com"

        def authenticate(self) -> dict[str, str]:
            return {"Authorization": "Bearer token"}

    class FakeWorkspace:
        config = FakeConfig()

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "SELECT 1"}}]}

    def fake_post(url, headers, json, timeout):
        calls["url"] = url
        calls["headers"] = headers
        calls["json"] = json
        calls["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("dbxcarta.client.local_generation.requests.post", fake_post)

    sql = generate_sql_local(FakeWorkspace(), "chat-endpoint", "prompt", timeout_sec=7)

    assert sql == "SELECT 1"
    assert calls["url"].endswith("/serving-endpoints/chat-endpoint/invocations")
    assert calls["headers"] == {"Authorization": "Bearer token"}
    assert calls["json"]["messages"] == [{"role": "user", "content": "prompt"}]
    assert calls["json"]["temperature"] == 0.0
    assert calls["timeout"] == 7
