"""Graph-level metadata node shared across all data models."""

from datetime import datetime

from pydantic import BaseModel, Field


class NeocartaGraph(BaseModel):
    """A singleton metadata node describing the Neocarta-managed graph.

    A graph contains at most one node with the ``__neocarta_graph__`` label.
    The node tracks the versions of the ``neocarta`` library that wrote to
    the graph and is used by the MCP server to detect mismatches between
    the writer and reader versions.
    """

    initial_version: str = Field(
        ...,
        description="The neocarta version that first wrote to this graph",
    )
    latest_version: str = Field(
        ...,
        description="The neocarta version that most recently wrote to this graph",
    )
    create_date: datetime = Field(
        ...,
        description="UTC timestamp at which the graph was created",
    )
    last_updated: datetime = Field(
        ...,
        description="UTC timestamp at which the graph was last updated",
    )
