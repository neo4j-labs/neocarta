"""Static metadata-FK rule tables.

The metadata FK strategy itself runs in Spark (`fk.inference`); this module
is the single definition of the small static rule tables that strategy
expands into native `Column` expressions and broadcast lookups at
plan-construction time. Keeping the tables here (not inlined in
`inference`) preserves one authoritative source per rule.

- `NameMatchKind` — exact vs. suffix name-match branch.
- `_SCORE_TABLE` — score keyed by (name kind, PK evidence, comment overlap).
- `_STEM_SUFFIXES` — FK-stem suffixes stripped for the suffix branch.
- `_STOPWORDS` — comment tokens dropped before the overlap check.
"""

from __future__ import annotations

from enum import Enum

from dbxcarta.spark.ingest.fk.common import PKEvidence


class NameMatchKind(Enum):
    EXACT = "exact"
    SUFFIX = "suffix"


_SCORE_TABLE: dict[tuple[NameMatchKind, PKEvidence, bool], float] = {
    (NameMatchKind.EXACT, PKEvidence.DECLARED_PK, True): 0.95,
    (NameMatchKind.EXACT, PKEvidence.DECLARED_PK, False): 0.90,
    (NameMatchKind.EXACT, PKEvidence.UNIQUE_OR_HEUR, True): 0.88,
    (NameMatchKind.EXACT, PKEvidence.UNIQUE_OR_HEUR, False): 0.83,
    (NameMatchKind.SUFFIX, PKEvidence.DECLARED_PK, True): 0.88,
    (NameMatchKind.SUFFIX, PKEvidence.DECLARED_PK, False): 0.83,
    (NameMatchKind.SUFFIX, PKEvidence.UNIQUE_OR_HEUR, True): 0.82,
    (NameMatchKind.SUFFIX, PKEvidence.UNIQUE_OR_HEUR, False): 0.78,
}

_STEM_SUFFIXES = ("_id", "_fk", "_ref")

# Dropped from comment-token sets before overlap check. len>=4 filter in
# inference._comment_tokens_expr makes the short stops redundant; kept for
# spec parity and so future edits to the length floor don't re-introduce
# bleed.
_STOPWORDS = frozenset(
    {
        "the",
        "of",
        "and",
        "a",
        "an",
        "to",
        "for",
        "id",
        "column",
        "table",
    }
)
