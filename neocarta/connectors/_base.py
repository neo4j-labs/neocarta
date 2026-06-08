"""Base protocols defining the public connector contract.

See ``.claude/skills/add-source-connector/connector-contract.md`` for the prose specification. These
protocols make the contract executable: conformance tests assert that every
connector in :mod:`neocarta.connectors` matches one of them.

Two protocols, one per connector kind:

- :class:`SourceConnectorProtocol` — connectors that read an external system and
  ingest into Neo4j (BigQuery, Dataplex, query-log file readers).
- :class:`FormatConnectorProtocol` — connectors for portable file formats that
  also support exporting Neo4j data back out (CSV, OSI YAML).

Both protocols use :class:`runtime_checkable` so ``isinstance(connector, ...)``
works at runtime — conformance tests rely on this.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SourceConnectorProtocol(Protocol):
    """Public contract for source connectors (ingest only).

    Concrete connectors may extend the signatures with source-specific
    arguments (e.g. ``dataset_id``, ``query_log_file``), but the *names* and
    the orchestration shape must match.
    """

    def extract(self, *args: Any, **kwargs: Any) -> None:
        """Read from the external system and populate the extractor cache."""
        ...

    def transform(self) -> None:
        """Convert cached extract state into graph data model objects."""
        ...

    def load(self) -> None:
        """Write transformed objects into Neo4j."""
        ...

    def ingest(self, *args: Any, **kwargs: Any) -> None:
        """Run extract → transform → load and record neocarta graph metadata."""
        ...

    def run(self, *args: Any, **kwargs: Any) -> None:
        """Deprecated wrapper around :meth:`ingest`.

        Must emit a :class:`DeprecationWarning` and delegate to :meth:`ingest`.
        Removed after approximately three releases.
        """
        ...


@runtime_checkable
class FormatConnectorProtocol(SourceConnectorProtocol, Protocol):
    """Public contract for format connectors (ingest + export).

    Format connectors satisfy the full source-connector contract and add an
    :meth:`export` orchestrator. The export direction's internal stages
    (graph read, source-format build, file write) are private — only
    :meth:`export` is part of the public surface.
    """

    def export(self, *args: Any, **kwargs: Any) -> None:
        """Read an entity from Neo4j and write it out in the connector's format."""
        ...
