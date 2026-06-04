#!/usr/bin/env python3
"""Filter and deduplicate question batch files, producing a clean questions JSON for upload.

Usage (from examples/dense-schema/):
    python filter_questions.py                        # default: drops single_table_filter, deduplicates
    python filter_questions.py --keep-all-shapes      # deduplication only
    python filter_questions.py --batch-dir .cache/questions_500 --output questions_500_clean.json

The output format matches the dbxcarta client question schema:
    question_id, question, reference_sql, schema, source_id, shape
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_DEFAULT_EXCLUDE: set[str] = {"single_table_filter"}
_SCHEMA_RE = re.compile(r"`([^`]+)`\.\`([^`]+)`\.\`[^`]+`")

# Fallback (catalog, schema) when no fully-qualified table reference is found.
# dense materializes into its own data catalog, so this is dense-schema-example,
# not the old shared-with-schemapile catalog.
_DEFAULT_CATALOG_SCHEMA: tuple[str, str] = ("dense-schema-example", "dense-1000")


def _detect_schema(sql: str) -> tuple[str, str]:
    """Return (catalog, schema) from the first fully-qualified table reference."""
    m = _SCHEMA_RE.search(sql)
    if m:
        return m.group(1), m.group(2)
    return _DEFAULT_CATALOG_SCHEMA


def _load_batches(batch_dir: Path) -> list[dict]:
    questions = []
    for path in sorted(batch_dir.glob("batch_*.json")):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, dict):
                continue
            shape = str(item.get("shape", "")).strip()
            question = str(item.get("question", "")).strip()
            sql = str(item.get("sql", "")).strip()
            if shape and question and sql:
                questions.append({"shape": shape, "question": question, "sql": sql})
    return questions


def _format_output(
    questions: list[dict],
    catalog: str,
    schema: str,
    source_id: str,
    id_prefix: str,
) -> list[dict]:
    return [
        {
            "question_id": f"{id_prefix}_{i:04d}",
            "question": q["question"],
            "reference_sql": q["sql"],
            "schema": schema,
            "source_id": source_id,
            "shape": q["shape"],
        }
        for i, q in enumerate(questions)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="filter_questions",
        description="Filter and deduplicate question batch files for upload.",
    )
    parser.add_argument(
        "--batch-dir",
        type=Path,
        default=Path(".cache/questions_1000"),
        help="Directory containing batch_*.json files (default: .cache/questions_1000)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("questions.json"),
        help="Output path for the cleaned questions JSON (default: questions.json)",
    )
    parser.add_argument(
        "--keep-all-shapes",
        action="store_true",
        help="Keep all shapes including single_table_filter. Only deduplication is applied.",
    )
    parser.add_argument(
        "--exclude-shapes",
        nargs="+",
        metavar="SHAPE",
        default=None,
        help=(
            "Shapes to exclude. Overrides the default exclusion of single_table_filter. "
            "Valid values: single_table_filter, two_table_join, aggregation"
        ),
    )
    parser.add_argument(
        "--id-prefix",
        default="ds",
        help="Prefix for question_id values (default: ds)",
    )
    args = parser.parse_args()

    if not args.batch_dir.is_dir():
        print(f"error: batch dir not found: {args.batch_dir}", file=sys.stderr)
        return 1

    raw = _load_batches(args.batch_dir)
    if not raw:
        print("error: no questions found in batch dir", file=sys.stderr)
        return 1

    # Determine which shapes to exclude
    if args.keep_all_shapes:
        exclude = set()
    elif args.exclude_shapes is not None:
        exclude = set(args.exclude_shapes)
    else:
        exclude = _DEFAULT_EXCLUDE

    # Filter shapes
    shape_filtered = [q for q in raw if q["shape"] not in exclude]

    # Deduplicate by exact SQL, preserving order
    seen: set[str] = set()
    deduped: list[dict] = []
    for q in shape_filtered:
        if q["sql"] not in seen:
            seen.add(q["sql"])
            deduped.append(q)

    # Detect catalog/schema from first SQL
    catalog, schema = _detect_schema(deduped[0]["sql"]) if deduped else _DEFAULT_CATALOG_SCHEMA
    source_id = f"synthetic_{schema.split('_')[-1]}" if "_" in schema else schema

    output = _format_output(deduped, catalog, schema, source_id, args.id_prefix)
    args.output.write_text(json.dumps(output, indent=2))

    # Stats
    removed_shapes = len(raw) - len(shape_filtered)
    removed_dups = len(shape_filtered) - len(deduped)
    shape_counts = {}
    for q in deduped:
        shape_counts[q["shape"]] = shape_counts.get(q["shape"], 0) + 1

    print(f"Input:          {len(raw)} questions")
    if exclude:
        print(f"Excluded shapes ({', '.join(sorted(exclude))}): -{removed_shapes}")
    print(f"Duplicates removed: -{removed_dups}")
    print(f"Output:         {len(deduped)} questions → {args.output}")
    print(f"Shape breakdown: {shape_counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
