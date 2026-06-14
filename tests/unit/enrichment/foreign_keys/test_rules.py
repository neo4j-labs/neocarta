"""Tests for the Spark-free foreign-key inference rule layer.

These cover the pure-Python primitives in
:mod:`neocarta.enrichment.foreign_keys.rules` — type canonicalization, comment
tokenization, the ``_id`` index, PK-evidence classification, source/target
match keys, and the score table. They are the migrated, Spark-free successor to
the dbxcarta ``fk.common`` / ``fk.metadata`` rule tests, adapted to the new API
where PK-likeness is a ``is_primary_key`` boolean on the column (read from the
graph) rather than an information_schema constraint index.
"""

from __future__ import annotations

from neocarta.enrichment.foreign_keys.rules import (
    ColumnMeta,
    NameMatchKind,
    PKEvidence,
    build_id_cols_index,
    canonicalize,
    comment_tokens,
    pk_evidence,
    score,
    source_match_keys,
    target_match_keys,
    types_compatible,
)


def _col(
    table: str,
    column: str,
    *,
    data_type: str = "BIGINT",
    description: str | None = None,
    is_primary_key: bool = False,
    catalog: str = "c",
    schema: str = "s",
) -> ColumnMeta:
    return ColumnMeta(
        col_id=f"{catalog}.{schema}.{table}.{column}",
        catalog=catalog,
        schema=schema,
        table=table,
        column=column,
        data_type=data_type,
        description=description,
        is_primary_key=is_primary_key,
    )


# --- canonicalize / types_compatible ----------------------------------------


def test_canonicalize_int_family_collapses_to_integer():
    assert canonicalize("BIGINT") == ("INTEGER", None)
    assert canonicalize("INT") == ("INTEGER", None)
    assert canonicalize("LONG") == ("INTEGER", None)
    assert canonicalize("SMALLINT") == ("INTEGER", None)


def test_canonicalize_string_length_stripped():
    """STRING, STRING(n), VARCHAR, VARCHAR(n), CHAR all canonicalize to STRING."""
    assert canonicalize("STRING") == ("STRING", None)
    assert canonicalize("STRING(255)") == ("STRING", None)
    assert canonicalize("VARCHAR(10)") == ("STRING", None)
    assert canonicalize("CHAR") == ("STRING", None)


def test_canonicalize_decimal_keeps_scale_drops_precision():
    """DECIMAL(10,2) == DECIMAL(18,2); DECIMAL(10,2) != DECIMAL(10,0)."""
    assert canonicalize("DECIMAL(10,2)") == ("DECIMAL", "2")
    assert canonicalize("DECIMAL(18,2)") == ("DECIMAL", "2")
    assert canonicalize("NUMERIC(10,0)") == ("DECIMAL", "0")


def test_types_compatible_decimal_same_scale_different_precision():
    assert types_compatible("DECIMAL(10,2)", "DECIMAL(18,2)") is True
    assert types_compatible("DECIMAL(10,2)", "DECIMAL(10,0)") is False


def test_types_compatible_int_and_bigint():
    assert types_compatible("INT", "BIGINT") is True


def test_types_compatible_int_and_string():
    assert types_compatible("INT", "STRING") is False


# --- comment_tokens ----------------------------------------------------------


def test_comment_tokens_drops_short_and_stopword_tokens():
    """Tokens shorter than 4 chars and stopwords are dropped, rest lower-cased."""
    tokens = comment_tokens("The customer identifier for an order")
    assert "customer" in tokens
    assert "identifier" in tokens
    assert "the" not in tokens  # stopword
    assert "for" not in tokens  # < 4 chars
    assert "an" not in tokens  # < 4 chars


def test_comment_tokens_empty_for_blank_or_none():
    assert comment_tokens(None) == frozenset()
    assert comment_tokens("") == frozenset()


# --- build_id_cols_index -----------------------------------------------------


def test_build_id_cols_index_groups_by_table_and_filters_non_id_suffix():
    cols = [
        _col("users", "id"),
        _col("users", "user_id"),
        _col("users", "email"),  # no _id suffix -> excluded
        _col("orders", "order_id"),
    ]
    index = build_id_cols_index(cols)
    assert set(index[("c", "s", "users")]) == {"user_id"}
    assert set(index[("c", "s", "orders")]) == {"order_id"}
    assert "id" not in index[("c", "s", "users")]  # 'id' doesn't end in '_id'


# --- pk_evidence: declared beats heuristic -----------------------------------


def test_pk_evidence_declared_pk_wins():
    tgt = _col("users", "id", is_primary_key=True)
    assert pk_evidence(tgt, build_id_cols_index([tgt])) is PKEvidence.DECLARED_PK


def test_pk_evidence_id_heuristic_fires_without_declared_pk():
    """An `id` column with no declared PK still qualifies heuristically."""
    tgt = _col("users", "id", is_primary_key=False)
    assert pk_evidence(tgt, build_id_cols_index([tgt])) is PKEvidence.UNIQUE_OR_HEUR


def test_pk_evidence_table_id_heuristic_requires_sole_id_col():
    """`{table}_id` qualifies only when it is the SOLE _id-suffixed column."""
    users_id = _col("users", "users_id")
    other_id = _col("users", "other_id")
    index = build_id_cols_index([users_id, other_id])
    assert pk_evidence(users_id, index) is None


def test_pk_evidence_sole_table_id_col_qualifies():
    users_id = _col("users", "users_id")
    index = build_id_cols_index([users_id])
    assert pk_evidence(users_id, index) is PKEvidence.UNIQUE_OR_HEUR


def test_pk_evidence_returns_none_for_non_pk_like_column():
    tgt = _col("users", "email")
    assert pk_evidence(tgt, build_id_cols_index([tgt])) is None


# --- source / target match keys ----------------------------------------------


def test_source_match_keys_exact_plus_stem_suffixes():
    keys = source_match_keys("customer_id")
    assert (NameMatchKind.EXACT, "customer_id") in keys
    assert (NameMatchKind.SUFFIX, "customer") in keys


def test_source_match_keys_no_suffix_for_bare_name():
    keys = source_match_keys("name")
    assert keys == [(NameMatchKind.EXACT, "name")]


def test_target_match_keys_id_expands_to_table_singular_forms():
    keys = target_match_keys("id", "customers")
    assert (NameMatchKind.EXACT, "id") in keys
    assert (NameMatchKind.SUFFIX, "customers") in keys
    assert (NameMatchKind.SUFFIX, "customer") in keys  # trailing 's' stripped


def test_target_match_keys_es_plural_stripped():
    keys = target_match_keys("id", "boxes")
    assert (NameMatchKind.SUFFIX, "box") in keys  # trailing 'es' stripped


def test_target_match_keys_non_id_column_is_exact_only():
    keys = target_match_keys("customer_id", "orders")
    assert keys == [(NameMatchKind.EXACT, "customer_id")]


# --- score table -------------------------------------------------------------


def test_score_exact_declared_pk_with_comment_is_highest():
    assert score(NameMatchKind.EXACT, PKEvidence.DECLARED_PK, True) == 0.95


def test_score_suffix_heuristic_no_comment_below_threshold():
    """Suffix + heuristic + no comment is 0.78, below the 0.8 acceptance floor."""
    assert score(NameMatchKind.SUFFIX, PKEvidence.UNIQUE_OR_HEUR, False) == 0.78
