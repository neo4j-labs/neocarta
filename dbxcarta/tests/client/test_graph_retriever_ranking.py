"""Unit tests for combined FK+cosine re-ranking logic in graph_retriever."""

from __future__ import annotations

from dbxcarta.client.graph_retriever import _rank_by_combined_score

# ---------------------------------------------------------------------------
# _rank_by_combined_score
# ---------------------------------------------------------------------------


def test_high_cosine_beats_high_fk_at_alpha_0():
    """At alpha=0 (pure cosine), highest cosine score wins regardless of FK."""
    fk_pairs = [("t_fk", 0.99), ("t_cos", 0.10)]
    cosine_scores = {"t_fk": 0.01, "t_cos": 0.95}
    ranked = _rank_by_combined_score(fk_pairs, cosine_scores, alpha=0.0, max_tables=2)
    assert ranked[0] == "t_cos"
    assert ranked[1] == "t_fk"


def test_high_fk_beats_high_cosine_at_alpha_1():
    """At alpha=1 (pure FK), highest FK confidence wins regardless of cosine."""
    fk_pairs = [("t_fk", 0.99), ("t_cos", 0.10)]
    cosine_scores = {"t_fk": 0.01, "t_cos": 0.95}
    ranked = _rank_by_combined_score(fk_pairs, cosine_scores, alpha=1.0, max_tables=2)
    assert ranked[0] == "t_fk"
    assert ranked[1] == "t_cos"


def test_combined_score_at_alpha_half():
    """At alpha=0.5, weak FK + high cosine ranks above strong FK + zero cosine."""
    # t_cross: fk=0.3, cosine=0.9 → combined = 0.5*0.3 + 0.5*0.9 = 0.6
    # t_intra: fk=0.95, cosine=0.0 → combined = 0.5*0.95 + 0.5*0.0 = 0.475
    fk_pairs = [("t_intra", 0.95), ("t_cross", 0.30)]
    cosine_scores = {"t_intra": 0.0, "t_cross": 0.9}
    ranked = _rank_by_combined_score(fk_pairs, cosine_scores, alpha=0.5, max_tables=2)
    assert ranked[0] == "t_cross", (
        "cross-domain table with high cosine should outrank intra-domain "
        "table with strong FK but zero cosine similarity"
    )


def test_missing_cosine_score_defaults_to_zero():
    """Tables absent from cosine_scores get 0.0 cosine and rank by FK only."""
    fk_pairs = [("t_no_cos", 0.80), ("t_has_cos", 0.40)]
    cosine_scores = {"t_has_cos": 0.50}
    # t_no_cos: 0.5*0.80 + 0.5*0.0 = 0.40
    # t_has_cos: 0.5*0.40 + 0.5*0.50 = 0.45
    ranked = _rank_by_combined_score(fk_pairs, cosine_scores, alpha=0.5, max_tables=2)
    assert ranked[0] == "t_has_cos"


def test_max_tables_cap_applied():
    """Result is capped at max_tables even when more candidates exist."""
    fk_pairs = [(f"t{i}", float(i) / 10) for i in range(10)]
    ranked = _rank_by_combined_score(fk_pairs, cosine_scores={}, alpha=1.0, max_tables=3)
    assert len(ranked) == 3


def test_empty_fk_pairs_returns_empty():
    ranked = _rank_by_combined_score([], {}, alpha=0.5, max_tables=10)
    assert ranked == []


def test_single_candidate_always_returned():
    ranked = _rank_by_combined_score([("t1", 0.5)], {"t1": 0.8}, alpha=0.5, max_tables=5)
    assert ranked == ["t1"]


def test_identical_scores_preserves_all_candidates():
    """Ties are broken by sort stability; all candidates within cap are returned."""
    fk_pairs = [("a", 0.5), ("b", 0.5), ("c", 0.5)]
    ranked = _rank_by_combined_score(fk_pairs, {}, alpha=0.5, max_tables=3)
    assert len(ranked) == 3
    assert set(ranked) == {"a", "b", "c"}
