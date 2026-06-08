"""Text2SQL agent factory."""

import os

from langchain.agents import create_agent
from langchain.tools import BaseTool
from langchain_litellm import ChatLiteLLM
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph

SYSTEM_PROMPT = """You are a Text2SQL agent and are tasked with answering
questions about our BigQuery dataset on ecommerce.

Use the metadata graph to collect relevant schema to inform your SQL queries.

Rules:
* Always ensure that tables are qualified with project and dataset names
* Always ensure you have the appropriate BigQuery schema from the Metadata Graph before write a query
* Return query results to the user in a readable format"""

DEFAULT_AGENT_MODEL = "gpt-4o-mini"


def create_text2sql_agent(mcp_tools: list[BaseTool]) -> CompiledStateGraph:
    """Create a Text2SQL LangGraph agent with the provided MCP tools."""
    model = ChatLiteLLM(model=os.getenv("AGENT_MODEL", DEFAULT_AGENT_MODEL))
    return create_agent(
        model=model,
        tools=mcp_tools,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=InMemorySaver(),
    )
