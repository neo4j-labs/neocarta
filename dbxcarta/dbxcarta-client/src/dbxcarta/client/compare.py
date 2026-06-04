"""Result-set normalization and comparison for client SQL grading."""

from __future__ import annotations

from collections import Counter
from itertools import combinations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

# Result-set comparison algorithm boundaries. Not runtime tunables.
COMPARE_ROW_THRESHOLD = 500
LARGE_COUNT_TOLERANCE = 0.10
LARGE_SAMPLE_MATCH_RATE = 0.80


def stringify_cell(value: Any) -> str:
    """Stringify a result-set cell with case-insensitive string comparison."""
    if value is None:
        return "NULL"
    return str(value).casefold()


def normalize_row(row: Sequence[Any], col_names: Sequence[str] = ()) -> tuple[str, ...]:
    """Sort stringified cell values, making column order and aliases irrelevant."""
    return tuple(sorted(stringify_cell(v) for v in row))


def normalize_result_set(
    col_names: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> list[tuple[str, ...]]:
    normalized = [normalize_row(row, col_names) for row in rows]
    return sorted(normalized)


def project_to_ref_columns(
    gen_cols: list[str],
    gen_rows: list[list],
    ref_cols: list[str],
) -> tuple[list[str], list[list]]:
    """Project generated rows to reference columns when ref names are a subset."""
    if not ref_cols or not gen_cols or len(ref_cols) >= len(gen_cols):
        return gen_cols, gen_rows
    gen_lower = [c.casefold() for c in gen_cols]
    ref_lower = [c.casefold() for c in ref_cols]
    if not set(ref_lower).issubset(set(gen_lower)):
        return gen_cols, gen_rows
    idx = [gen_lower.index(c) for c in ref_lower]
    projected_rows = [[row[i] for i in idx] for row in gen_rows]
    return list(ref_cols), projected_rows


def _subset_matches(
    gen_cols: list[str],
    gen_rows: list[list],
    ref_norm: list[tuple[str, ...]],
    n: int,
) -> bool:
    """Return True if any n-column subset of gen_rows normalizes to ref_norm.

    Fallback for when name projection fails because the model aliased columns
    (e.g. SUM(amount) -> total_amount) while also adding extra columns.
    Only called when len(gen_cols) - n <= 4 to keep combinations tractable.
    """
    for indices in combinations(range(len(gen_cols)), n):
        proj_cols = [gen_cols[i] for i in indices]
        proj_rows = [[row[i] for i in indices] for row in gen_rows]
        if normalize_result_set(proj_cols, proj_rows) == ref_norm:
            return True
    return False


def is_row_superset(
    ref_norm: list[tuple[str, ...]],
    gen_norm: list[tuple[str, ...]],
) -> bool:
    """True when every reference row appears in generated at least as often."""
    ref_counter = Counter(ref_norm)
    gen_counter = Counter(gen_norm)
    return all(gen_counter[row] >= count for row, count in ref_counter.items())


def compare_result_sets(
    gen_cols: list[str],
    gen_rows: list[list],
    ref_cols: list[str],
    ref_rows: list[list],
) -> tuple[bool, str | None]:
    """Compare result sets, ignoring column ordering and string case."""
    gen_cols, gen_rows = project_to_ref_columns(gen_cols, gen_rows, ref_cols)

    gen_count = len(gen_rows)
    ref_count = len(ref_rows)

    if gen_count >= COMPARE_ROW_THRESHOLD or ref_count >= COMPARE_ROW_THRESHOLD:
        if (
            gen_count < ref_count
            and ref_count > 0
            and (ref_count - gen_count) / ref_count > LARGE_COUNT_TOLERANCE
        ):
            return False, (
                "row count divergence >10% below reference: "
                f"generated={gen_count} reference={ref_count}"
            )
        gen_sorted = normalize_result_set(gen_cols, gen_rows)
        ref_sorted = normalize_result_set(ref_cols, ref_rows)
        if gen_count > ref_count and is_row_superset(ref_sorted, gen_sorted):
            return True, None
        sample_size = min(50, gen_count)
        stride = max(1, gen_count // sample_size) if sample_size else 1
        gen_sample = gen_sorted[::stride][:sample_size]
        ref_sample = ref_sorted[::stride][:sample_size]
        if not gen_sample:
            return True, None
        match_rate = sum(g == r for g, r in zip(gen_sample, ref_sample, strict=False)) / len(
            gen_sample
        )
        if match_rate < LARGE_SAMPLE_MATCH_RATE:
            return False, (f"sampled match rate {match_rate:.1%} < {LARGE_SAMPLE_MATCH_RATE:.0%}")
        return True, None

    gen_sorted = normalize_result_set(gen_cols, gen_rows)
    ref_sorted = normalize_result_set(ref_cols, ref_rows)

    if gen_count == ref_count:
        if gen_sorted == ref_sorted:
            return True, None
        # Name projection failed due to column aliases on extra columns. Try
        # all column subsets of size len(ref_cols). Guard: at most 4 extra
        # columns so combinations stay tractable.
        if (
            len(gen_cols) > len(ref_cols)
            and len(gen_cols) - len(ref_cols) <= 4
            and _subset_matches(gen_cols, gen_rows, ref_sorted, len(ref_cols))
        ):
            return True, None
        return False, "result set values differ"

    return False, f"row count mismatch: generated={gen_count} reference={ref_count}"
