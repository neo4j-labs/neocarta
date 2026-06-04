"""Phase 3: relationship-write partitioning helper.

`run._rel_partition` is the single place that decides relationship-write
parallelism. The risk is not the partition count but the *path*: `n <= 1`
must take `coalesce(1)` (no shuffle, byte-for-byte identical to the
historical write), and must never take `repartition(1)` (a full shuffle
that is not equivalent). A spy DataFrame records which method ran so the
path is asserted directly, without standing up Spark.
"""

from __future__ import annotations

import pytest
from dbxcarta.spark.run import _rel_partition


class _SpyDF:
    """Records coalesce/repartition calls; each returns a sentinel result."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def coalesce(self, n: int) -> str:
        self.calls.append(("coalesce", n))
        return "coalesced"

    def repartition(self, n: int) -> str:
        self.calls.append(("repartition", n))
        return "repartitioned"


@pytest.mark.parametrize("n", [1, 0, -1])
def test_n_le_1_coalesces_and_never_repartitions(n: int) -> None:
    df = _SpyDF()
    out = _rel_partition(df, n)
    assert df.calls == [("coalesce", 1)]
    assert out == "coalesced"


@pytest.mark.parametrize("n", [2, 4, 16])
def test_n_gt_1_repartitions_to_n_and_never_coalesces(n: int) -> None:
    df = _SpyDF()
    out = _rel_partition(df, n)
    assert df.calls == [("repartition", n)]
    assert out == "repartitioned"
