"""Local SQL generation through Databricks Model Serving."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import requests

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient


class LocalGenerationError(RuntimeError):
    """Raised when a local serving endpoint call cannot produce text."""


def generate_sql_local(
    ws: WorkspaceClient,
    endpoint: str,
    prompt: str,
    *,
    timeout_sec: int = 60,
) -> str:
    """Call a Databricks serving endpoint and return generated text."""
    headers = ws.config.authenticate()
    url = f"{ws.config.host.rstrip('/')}/serving-endpoints/{endpoint}/invocations"
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 1024,
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout_sec,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise LocalGenerationError(f"serving endpoint call failed for {endpoint!r}: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise LocalGenerationError(f"serving endpoint {endpoint!r} did not return JSON") from exc

    text = extract_generated_text(data)
    if not text:
        raise LocalGenerationError(f"serving endpoint {endpoint!r} returned no generated text")
    return text


def extract_generated_text(data: Any) -> str | None:
    """Extract generated text from common Databricks serving response shapes."""
    if data is None:
        return None
    if isinstance(data, str):
        return data
    if isinstance(data, list):
        parts = [extract_generated_text(item) for item in data]
        text_parts = [part for part in parts if part]
        return "\n".join(text_parts) if text_parts else None
    if not isinstance(data, dict):
        return str(data)

    if error := data.get("error"):
        raise LocalGenerationError(str(error))

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0]
        if isinstance(choice, dict):
            message = choice.get("message")
            if isinstance(message, dict):
                content = _content_to_text(message.get("content"))
                if content:
                    return content
            content = _content_to_text(choice.get("text") or choice.get("content"))
            if content:
                return content

    for key in ("result", "response", "generated_text", "text", "output"):
        content = _content_to_text(data.get(key))
        if content:
            return content

    for key in ("predictions", "data"):
        content = extract_generated_text(data.get(key))
        if content:
            return content

    return None


def _content_to_text(content: Any) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                part = _content_to_text(
                    item.get("text") or item.get("content") or item.get("result")
                )
                if part:
                    parts.append(part)
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts) if parts else None
    if isinstance(content, dict):
        for key in ("text", "content", "result"):
            value = _content_to_text(content.get(key))
            if value:
                return value
    return str(content)
