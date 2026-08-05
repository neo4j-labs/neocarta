"""Unit tests for LiteLLMDescriptionConnector."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from neocarta.enrichment.descriptions import LiteLLMDescriptionConnector
from neocarta.enrichment.descriptions.litellm_description import _build_context_prompt

_COMPLETE = "neocarta.enrichment.descriptions.litellm_description.litellm.completion"


def _fake_response(text: str) -> SimpleNamespace:
    """Build a SimpleNamespace mimicking litellm's chat completion response shape."""
    message = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def test_default_model_and_system_prompt():
    connector = LiteLLMDescriptionConnector(neo4j_driver=MagicMock())
    assert connector.generation_model == "gpt-4o-mini"
    assert "data documentation assistant" in connector.system_prompt.lower()


def test_custom_system_prompt_overrides_default():
    connector = LiteLLMDescriptionConnector(
        neo4j_driver=MagicMock(), system_prompt="Custom prompt."
    )
    assert connector.system_prompt == "Custom prompt."


def test_generate_description_sync_returns_stripped_content():
    connector = LiteLLMDescriptionConnector(neo4j_driver=MagicMock())
    fake_response = _fake_response("  A table of customer orders.  ")
    context = {"node_label": "Table", "name": "orders"}

    with patch(_COMPLETE, return_value=fake_response) as mock_complete:
        result = connector._generate_description_sync(context)

    assert result == "A table of customer orders."
    assert mock_complete.call_args.kwargs["model"] == "gpt-4o-mini"


def test_generate_description_sync_returns_none_on_failure():
    connector = LiteLLMDescriptionConnector(neo4j_driver=MagicMock())
    context = {"node_label": "Table", "name": "orders"}

    with patch(_COMPLETE, side_effect=RuntimeError("boom")):
        result = connector._generate_description_sync(context)

    assert result is None


def test_litellm_kwargs_forwarded_to_completion_call():
    connector = LiteLLMDescriptionConnector(
        neo4j_driver=MagicMock(), litellm_kwargs={"temperature": 0.2}
    )
    fake_response = _fake_response("A description.")
    context = {"node_label": "Table", "name": "orders"}

    with patch(_COMPLETE, return_value=fake_response) as mock_complete:
        connector._generate_description_sync(context)

    assert mock_complete.call_args.kwargs["temperature"] == 0.2


def test_build_context_prompt_table_includes_schema_and_columns():
    context = {
        "node_label": "Table",
        "name": "orders",
        "schema_name": "sales",
        "column_names": ["id", "total", "customer_id"],
    }
    prompt = _build_context_prompt(context)
    assert "Table" in prompt
    assert "orders" in prompt
    assert "sales" in prompt
    assert "total" in prompt


def test_build_context_prompt_column_includes_example_values():
    context = {
        "node_label": "Column",
        "name": "status",
        "table_name": "orders",
        "sibling_column_names": ["id", "total"],
        "column_type": "VARCHAR",
        "example_values": ["pending", "shipped", "delivered"],
    }
    prompt = _build_context_prompt(context)
    assert "Column" in prompt
    assert "status" in prompt
    assert "VARCHAR" in prompt
    assert "pending" in prompt


def test_build_context_prompt_handles_missing_optional_fields():
    context = {"node_label": "Schema", "name": "sales"}
    prompt = _build_context_prompt(context)
    assert "Schema" in prompt
    assert "sales" in prompt
