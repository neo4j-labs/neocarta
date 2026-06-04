"""Retriever ABC and ContextBundle for the graph_rag arm."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

_PER_COLUMN_SAMPLE_LIMIT = 10


@dataclass
class ColumnEntry:
    table_fqn: str
    column_name: str
    data_type: str
    comment: str = ""
    column_id: str = ""


@dataclass
class JoinLine:
    predicate: str
    source: str | None = None
    confidence: float | None = None


def _join_annotation(jl: JoinLine) -> str:
    parts: list[str] = []
    if jl.source:
        parts.append(jl.source)
    if jl.confidence is not None:
        parts.append(f"conf={jl.confidence:.2f}")
    if not parts:
        return ""
    return "  [" + ", ".join(parts) + "]"


@dataclass
class ContextBundle:
    columns: list[ColumnEntry] = field(default_factory=list)
    values: dict[str, list[str]] = field(default_factory=dict)
    # Populated by GraphRetriever; empty for other arms.
    col_seed_ids: list[str] = field(default_factory=list)
    col_seed_scores: list[float] = field(default_factory=list)
    tbl_seed_ids: list[str] = field(default_factory=list)
    tbl_seed_scores: list[float] = field(default_factory=list)
    expansion_tbl_ids: list[str] = field(default_factory=list)
    selected_schemas: list[str] = field(default_factory=list)
    join_lines: list[JoinLine] = field(default_factory=list)

    @property
    def seed_ids(self) -> list[str]:
        """Backward-compatible combined seed IDs for older demos."""
        return self.col_seed_ids + self.tbl_seed_ids

    @property
    def criteria(self) -> list[str]:
        """Backward-compatible join predicate list for older demos."""
        return [join_line.predicate for join_line in self.join_lines]

    def to_text(self) -> str:
        if not self.columns:
            return ""
        lines: list[str] = []

        if self.selected_schemas:
            lines.append(f"Target schema: {', '.join(self.selected_schemas)}")
            lines.append("")

        lines.append("Tables:")
        current_table: str | None = None
        for col in self.columns:
            if col.table_fqn != current_table:
                if current_table is not None:
                    lines.append("")
                lines.append(f"Table: {col.table_fqn}")
                current_table = col.table_fqn
            suffix = f" — {col.comment}" if col.comment else ""
            lines.append(f"  {col.column_name} ({col.data_type}){suffix}")

        if self.join_lines:
            lines.append("")
            lines.append("Joins:")
            for jl in self.join_lines:
                lines.append(f"  {jl.predicate}{_join_annotation(jl)}")

        if self.values:
            id_to_entry: dict[str, ColumnEntry] = {
                c.column_id: c for c in self.columns if c.column_id
            }
            value_lines: list[str] = []
            for col_id, vals in self.values.items():
                if not vals:
                    continue
                entry = id_to_entry.get(col_id)
                if entry is None:
                    continue
                joined = ", ".join(vals[:_PER_COLUMN_SAMPLE_LIMIT])
                value_lines.append(f"  {entry.column_name} ({entry.table_fqn}): {joined}")
            if value_lines:
                lines.append("")
                lines.append("Sample values:")
                lines.extend(value_lines)

        return "\n".join(lines)


class Retriever(ABC):
    @abstractmethod
    def retrieve(self, question: str, embedding: list[float]) -> ContextBundle: ...

    def close(self) -> None:  # noqa: B027 — deliberate optional no-op override hook
        """Release any held resources.

        No-op by default. Implementations that hold a connection (e.g. the
        Neo4j-backed ``GraphRetriever``) override this. The shared graph_rag
        seam closes a retriever it constructs itself.
        """
