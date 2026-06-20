"""Connector for generating node descriptions via LiteLLM (multi-provider)."""

import logging
from typing import Any

import litellm
from neo4j import Driver

from .base import BaseDescriptionConnector

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = """\
You are a data documentation assistant. You generate concise, factual \
descriptions of database schema elements (schemas, tables, and columns) \
based on their name and immediate context in the data model.

Rules:
- Write 1-2 sentences, plain prose, no markdown formatting.
- Be specific and grounded in the provided context; do not invent facts.
- For columns, mention the likely meaning suggested by the name, type, and \
any example values, but do not assert business meaning you cannot infer.
- Do not repeat the raw context verbatim; synthesize it into a description.
- Return only the description text, with no preamble or quotation marks.\
"""


def _build_context_prompt(context: dict[str, Any]) -> str:
    """Render a node's context dict into a prompt describing what to generate."""
    node_label = context.get("node_label", "")
    name = context.get("name", "")

    lines = [f"Node type: {node_label}", f"Name: {name}"]

    if context.get("database_name"):
        lines.append(f"Parent database: {context.get('database_name') or '(unknown)'}")
    if context.get("table_names"):
        lines.append(f"Contains tables: {', '.join(context['table_names'])}")
    if context.get("schema_name"):
        lines.append(f"Parent schema: {context.get('schema_name') or '(unknown)'}")
    if context.get("column_names"):
        lines.append(f"Columns: {', '.join(context['column_names'])}")
    if context.get("table_name"):
        lines.append(f"Parent table: {context.get('table_name') or '(unknown)'}")
    if context.get("sibling_column_names"):
        lines.append(f"Sibling columns: {', '.join(context['sibling_column_names'])}")
    if context.get("column_type"):
        lines.append(f"Data type: {context['column_type']}")
    if context.get("example_values"):
        lines.append(f"Example values: {', '.join(str(v) for v in context['example_values'])}")

    return "\n".join(lines)


class LiteLLMDescriptionConnector(BaseDescriptionConnector):
    """Connector for generating node descriptions through LiteLLM.

    LiteLLM exposes a single, OpenAI-compatible interface over many
    providers (OpenAI, Azure OpenAI, Cohere, Bedrock, Vertex, Gemini,
    Ollama, ...). Provider routing is driven by the ``generation_model``
    string — e.g. ``"gpt-4o-mini"``, ``"gemini/gemini-1.5-flash"``.

    Authentication is read from provider-specific environment variables
    (``OPENAI_API_KEY``, ``GEMINI_API_KEY``, ``COHERE_API_KEY``, ``AZURE_*``,
    ``AWS_*``, etc.). For advanced setups (LiteLLM Proxy, custom endpoints),
    pass ``api_key`` / ``api_base`` via ``litellm_kwargs``.
    """

    def __init__(
        self,
        neo4j_driver: Driver,
        generation_model: str = "gpt-4o-mini",
        database_name: str = "neo4j",
        max_example_values: int = 5,
        system_prompt: str | None = None,
        litellm_kwargs: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the LiteLLM Description Connector.

        Parameters
        ----------
        neo4j_driver: Driver
            The Neo4j driver to use.
        generation_model: str
            The model identifier in LiteLLM format. Examples:
            ``"gpt-4o-mini"``, ``"gemini/gemini-1.5-flash"``.
        database_name: str
            The name of the Neo4j database to read context from / write
            descriptions to.
        max_example_values: int
            The maximum number of example Value nodes to fetch for a
            Column's context.
        system_prompt: Optional[str]
            Override the default system prompt used to instruct the model.
        litellm_kwargs: Optional[dict[str, Any]]
            Additional keyword arguments forwarded verbatim to
            ``litellm.completion`` / ``litellm.acompletion`` — e.g.
            ``api_key`` / ``api_base`` for LiteLLM Proxy / custom endpoints,
            or ``temperature``.
        """
        super().__init__(
            neo4j_driver=neo4j_driver,
            generation_model=generation_model,
            database_name=database_name,
            max_example_values=max_example_values,
        )
        self.system_prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT
        self._call_kwargs: dict[str, Any] = dict(litellm_kwargs) if litellm_kwargs else {}

    def _messages_for(self, context: dict[str, Any]) -> list[dict[str, str]]:
        """Build the chat messages for a single node's context."""
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": _build_context_prompt(context)},
        ]

    def _generate_description_sync(self, context: dict[str, Any]) -> str | None:
        """
        Generate a description for a single node's context (sync).

        Parameters
        ----------
        context: dict[str, Any]
            The node's context, as returned by ``get_node_context``.

        Returns:
        -------
        Optional[str]
            The generated description, or ``None`` if the API call fails.
        """
        try:
            response = litellm.completion(
                model=self.generation_model,
                messages=self._messages_for(context),
                **self._call_kwargs,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning("Description generation request failed (%s)", type(e).__name__)
            return None

    async def _generate_description_async(self, context: dict[str, Any]) -> str | None:
        """
        Generate a description for a single node's context (async).

        Parameters
        ----------
        context: dict[str, Any]
            The node's context, as returned by ``get_node_context``.

        Returns:
        -------
        Optional[str]
            The generated description, or ``None`` if the API call fails.
        """
        try:
            response = await litellm.acompletion(
                model=self.generation_model,
                messages=self._messages_for(context),
                **self._call_kwargs,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning("Description generation request failed (%s)", type(e).__name__)
            return None
