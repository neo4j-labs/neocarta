"""PySpark Column expressions for graph contract identifiers.

Spark-side counterparts of the Python id builders in
`neocarta.connectors.utils.generate_id` (`compose_id` and `generate_value_id`).
The Python and SQL implementations must agree byte-for-byte; this agreement is
maintained by keeping the two normalizations in lockstep (there is no separate
runtime check enforcing it).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyspark.sql import Column

# Characters translated in normalization: space→_, hyphen→_.
# Mirrors the substitutions in neocarta.connectors.utils.generate_id.compose_id.
_TRANSLATE_FROM = " -"
_TRANSLATE_TO = "__"


def id_expr_from_columns(*parts: Column) -> Column:
    """Return a PySpark Column expression equivalent to generate_id().

    Accepts arbitrary Column expressions, including literals. Use this when an
    identifier combines Python-known values with Spark row values.
    """
    from pyspark.sql import functions as F

    return F.lower(F.translate(F.concat_ws(".", *parts), _TRANSLATE_FROM, _TRANSLATE_TO))


def id_expr(*column_names: str) -> Column:
    """Return a PySpark Column expression equivalent to generate_id()."""
    from pyspark.sql import functions as F

    return id_expr_from_columns(*(F.col(c) for c in column_names))


def value_id_expr() -> Column:
    """Return a PySpark Column expression equivalent to generate_value_id().

    Expects the input DataFrame to expose `col_id` and `val`, matching the
    sample-value transform's intermediate schema.
    """
    from pyspark.sql import functions as F

    return F.concat(F.col("col_id"), F.lit("."), F.md5(F.col("val")))
