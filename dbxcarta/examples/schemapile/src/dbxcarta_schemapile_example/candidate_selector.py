"""Pick a stable subset of schemapile schemas for materialization and evaluation.

The output is the single source of truth read by both the materializer
(Phase 4) and the question generator (Phase 1, stage 1). Pinning the
candidate set keeps re-runs reproducible: the same slice + the same
selector parameters produce the same materialized tables and the same
LLM input, no matter how slice.py orders entries internally.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from dbxcarta_schemapile_example.config import SchemaPileConfig, load_config
from dbxcarta_schemapile_example.utils import load_dotenv_file

CANDIDATE_FORMAT_VERSION = 2

_ROW_CAP_PER_TABLE = 20
_SANITIZE_INVALID = re.compile(r"[^a-z0-9_]+")
_SANITIZE_LEADING_DIGIT = re.compile(r"^\d")


@dataclass(frozen=True)
class ForeignKey:
    columns: tuple[str, ...]
    foreign_table: str
    referred_columns: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": list(self.columns),
            "foreign_table": self.foreign_table,
            "referred_columns": list(self.referred_columns),
        }


@dataclass(frozen=True)
class TableSpec:
    name: str
    columns: tuple[tuple[str, str], ...]
    primary_keys: tuple[str, ...]
    foreign_keys: tuple[ForeignKey, ...]
    has_values: bool
    rows: tuple[tuple[Any, ...], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "columns": [{"name": n, "type": t} for n, t in self.columns],
            "primary_keys": list(self.primary_keys),
            "foreign_keys": [fk.to_dict() for fk in self.foreign_keys],
            "has_values": self.has_values,
            "rows": [list(r) for r in self.rows],
        }


@dataclass(frozen=True)
class CandidateSchema:
    source_id: str
    uc_schema: str
    rationale: str
    tables: tuple[TableSpec, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "uc_schema": self.uc_schema,
            "rationale": self.rationale,
            "tables": [t.to_dict() for t in self.tables],
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="dbxcarta-schemapile-select",
        description=(
            "Read the cached slice JSON and emit a fixed candidate-table JSON"
            " used by the materializer and the question generator."
        ),
    )
    parser.add_argument(
        "--dotenv",
        type=Path,
        default=Path(__file__).resolve().parents[2] / ".env",
        help="Path to the .env file to load before reading variables (default: example directory .env)",
    )
    args = parser.parse_args()
    load_dotenv_file(args.dotenv)
    config = load_config()

    if not config.slice_cache.is_file():
        raise FileNotFoundError(
            f"Slice cache not found at {config.slice_cache}. Run dbxcarta-schemapile-slice first."
        )

    slice_data = _load_slice(config.slice_cache)
    candidates = select_candidates(slice_data, config)

    config.candidate_cache.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format_version": CANDIDATE_FORMAT_VERSION,
        "source_slice": str(config.slice_cache),
        "selection_params": {
            "candidate_min_tables": config.candidate_min_tables,
            "candidate_max_tables": config.candidate_max_tables,
            "candidate_min_fk_edges": config.candidate_min_fk_edges,
            "candidate_require_data": config.candidate_require_data,
            "candidate_limit": config.candidate_limit,
        },
        "schemas": [c.to_dict() for c in candidates],
    }
    config.candidate_cache.write_text(json.dumps(payload, indent=2))
    print(
        f"[schemapile] wrote {len(candidates)} candidate schema(s) to {config.candidate_cache}",
        file=sys.stderr,
    )
    return 0


def select_candidates(
    slice_data: dict[str, Any],
    config: SchemaPileConfig,
) -> list[CandidateSchema]:
    """Apply filter + rank + cap to the slice and return chosen candidates.

    Ordering is deterministic given the same input: schemas with higher FK
    density per table are preferred, ties broken by source_id alphabetically.
    """
    raw = []
    for source_id, entry in slice_data.items():
        tables = _build_tables(entry.get("TABLES", {}))
        if not _passes_filters(tables, config):
            continue
        density = _density(tables)
        raw.append((source_id, tables, density))

    raw.sort(key=lambda r: (-r[2], r[0]))
    raw = raw[: config.candidate_limit]

    used_uc_schemas: set[str] = set()
    candidates: list[CandidateSchema] = []
    for source_id, tables, density in raw:
        uc_schema = _sanitize_schema_name(source_id, used=used_uc_schemas)
        used_uc_schemas.add(uc_schema)
        rationale = (
            f"tables={len(tables)}"
            f" fk_density={density:.2f}"
            f" data_tables={sum(1 for t in tables if t.has_values)}"
        )
        candidates.append(
            CandidateSchema(
                source_id=source_id,
                uc_schema=uc_schema,
                rationale=rationale,
                tables=tables,
            )
        )
    return candidates


def _passes_filters(tables: tuple[TableSpec, ...], config: SchemaPileConfig) -> bool:
    if not tables:
        return False
    if len(tables) < config.candidate_min_tables:
        return False
    if len(tables) > config.candidate_max_tables:
        return False
    fk_edges = sum(len(t.foreign_keys) for t in tables)
    if fk_edges < config.candidate_min_fk_edges:
        return False
    return not (config.candidate_require_data and not any(t.has_values for t in tables))


def _density(tables: tuple[TableSpec, ...]) -> float:
    if not tables:
        return 0.0
    return sum(len(t.foreign_keys) for t in tables) / len(tables)


def _build_tables(raw_tables: dict[str, Any]) -> tuple[TableSpec, ...]:
    specs: list[TableSpec] = []
    for name, raw in raw_tables.items():
        columns = raw.get("COLUMNS") or {}
        cols = tuple(
            (col_name, str(col_def.get("TYPE") or "").strip())
            for col_name, col_def in columns.items()
        )
        pks = tuple(raw.get("PRIMARY_KEYS") or [])
        fks = tuple(
            ForeignKey(
                columns=tuple(fk.get("COLUMNS") or []),
                foreign_table=str(fk.get("FOREIGN_TABLE") or ""),
                referred_columns=tuple(fk.get("REFERRED_COLUMNS") or []),
            )
            for fk in (raw.get("FOREIGN_KEYS") or [])
            if fk.get("FOREIGN_TABLE")
        )
        rows = _extract_rows(columns)
        has_values = bool(rows)
        specs.append(
            TableSpec(
                name=name,
                columns=cols,
                primary_keys=pks,
                foreign_keys=fks,
                has_values=has_values,
                rows=rows,
            )
        )
    return tuple(specs)


def _extract_rows(columns: dict[str, Any]) -> tuple[tuple[Any, ...], ...]:
    """Build position-aligned row tuples from per-column VALUES lists.

    Columns without VALUES contribute NULL for every row. Only the
    VALUES-having columns need to share a length; if they do not, the
    schemapile entry's values are not row-aligned and no rows are
    extracted.
    """
    if not columns:
        return ()
    columns_with_values: dict[str, list[Any]] = {}
    for name, col_def in columns.items():
        vals = col_def.get("VALUES")
        if vals:
            columns_with_values[name] = list(vals)
    if not columns_with_values:
        return ()
    lengths = {len(v) for v in columns_with_values.values()}
    if len(lengths) != 1:
        return ()
    n = min(lengths.pop(), _ROW_CAP_PER_TABLE)
    column_order = list(columns.keys())
    return tuple(
        tuple(
            columns_with_values[name][row_idx] if name in columns_with_values else None
            for name in column_order
        )
        for row_idx in range(n)
    )


def _sanitize_schema_name(source_id: str, *, used: set[str]) -> str:
    """Turn a schemapile entry id into a valid UC schema name, deduplicated."""
    base = source_id.lower()
    base = base.removesuffix(".sql")
    base = _SANITIZE_INVALID.sub("_", base)
    base = base.strip("_") or "schema"
    if _SANITIZE_LEADING_DIGIT.match(base) or not base.startswith("sp_"):
        base = f"sp_{base}"
    candidate = base
    counter = 1
    while candidate in used:
        counter += 1
        candidate = f"{base}_{counter}"
    return candidate


def _load_slice(path: Path) -> dict[str, Any]:
    try:
        import orjson

        return cast("dict[str, Any]", orjson.loads(path.read_bytes()))
    except ImportError:
        return cast("dict[str, Any]", json.loads(path.read_text()))


if __name__ == "__main__":
    raise SystemExit(main())
