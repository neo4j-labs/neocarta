"""Graph-contract identifier builders for the Databricks connector.

This module owns the connector's node-identity scheme. ``node_id`` uses the
shared ``neocarta.connectors.utils.generate_id`` recipe (``compose_id``) so the
Databricks connector's ids are uniform with the BigQuery / CSV / Dataplex
connectors. The Python and Spark implementations live side by side here so they
can be kept byte-identical.

Two id forms, two jobs
----------------------
``node_id``: the normalized, dot-joined identifier from ``compose_id``. Each part
is lowercased with spaces and hyphens folded to underscore, then joined with
``.``. This is the Neo4j MERGE key that the NODE KEY / uniqueness constraints are
enforced against. It is never parsed apart; the structural parts
are carried as their own node properties ``catalog`` / ``schema`` / ``table``.

``qualified_name``: the human-readable, *lossless* dotted path,
``catalog.schema.table.column``, lowercased but otherwise verbatim. Hyphens and
other legal characters are preserved. Stored as a node property for debugging and
hand-written Cypher. NOT the MERGE key.

The normalization is lossy: spaces and hyphens both fold to ``_``, so a schema
named ``graph-enriched-schema`` and one named ``graph_enriched_schema`` produce
the same ``node_id`` and MERGE collapses them into one node. This matches the
shared scheme used by every other connector; ``qualified_name`` keeps the
distinct readable paths even where the id folds them.

Byte-for-byte Python/Spark agreement
------------------------------------
Ids are produced on the driver (Python: ``node_id`` / ``qualified_name``) and
inside Spark (``node_id_expr`` / ``qualified_name_expr``); both must yield the
identical string for the same input or edges (matched by id) would not connect to
their nodes. Agreement is maintained by construction: both lowercase, both fold
space and hyphen to ``_``, and both join with ``.``. There is no separate runtime
check enforcing it, so keep the two in lockstep when editing either.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from neocarta.connectors.utils.generate_id import compose_id

if TYPE_CHECKING:
    from pyspark.sql import Column

# The part separator, matching the shared ``compose_id`` dotted join.
_PART_SEP = "."
# Characters folded to underscore by the shared ``_normalize`` (space, hyphen),
# replicated in Spark via ``translate``. Order pairs with ``_FOLD_TO``.
_FOLD_FROM = " -"
_FOLD_TO = "__"


def qualified_name(*parts: str) -> str:
    """Return the lossless, lowercased dotted path for an identifier tuple.

    ``catalog.schema.table.column`` (or any prefix), lowercased to match Unity
    Catalog's lowercase storage but otherwise verbatim. Hyphens and other legal
    characters are preserved. This is a node property only; it is never the MERGE
    key. The MERGE key is :func:`node_id`, which normalizes the same parts.

    Examples:
    --------
    >>> qualified_name("my-catalog", "sales", "orders")
    'my-catalog.sales.orders'
    """
    return _PART_SEP.join(p.lower() for p in parts)


def node_id(*parts: str) -> str:
    """Return the MERGE key for an identifier tuple: the shared ``compose_id``.

    Each part is lowercased with spaces and hyphens folded to underscore, then the
    parts are joined with ``.``. This is the canonical neocarta id recipe shared by
    every connector. The normalization is lossy; see the module docstring.

    Examples:
    --------
    >>> node_id("my-catalog", "sales", "orders")
    'my_catalog.sales.orders'
    """
    return compose_id(*parts)


def qualified_name_expr_from_columns(*parts: Column) -> Column:
    """Spark Column expression equal to :func:`qualified_name`.

    Accepts arbitrary Column expressions, including literals. ``lower`` after
    ``concat_ws('.')`` is identical to lowercasing each part then joining, since
    the ``.`` separator is unaffected by ``lower``. This keeps it byte-identical to
    the Python ``'.'.join(p.lower() ...)``.
    """
    from pyspark.sql import functions as F

    return F.lower(F.concat_ws(_PART_SEP, *parts))


def qualified_name_expr(*column_names: str) -> Column:
    """Spark Column expression equal to :func:`qualified_name`, by column name."""
    from pyspark.sql import functions as F

    return qualified_name_expr_from_columns(*(F.col(c) for c in column_names))


def node_id_expr_from_columns(*parts: Column) -> Column:
    """Spark Column expression equal to :func:`node_id`.

    Replicates ``compose_id`` byte-for-byte: ``translate`` folds space and hyphen
    to underscore over the lowercased dotted join. ``translate`` is character-wise,
    and the ``.`` separator is not in the fold set, so applying it after the join
    is identical to normalizing each part before joining. Accepts arbitrary Column
    expressions, including literals.
    """
    from pyspark.sql import functions as F

    return F.translate(qualified_name_expr_from_columns(*parts), _FOLD_FROM, _FOLD_TO)


def node_id_expr(*column_names: str) -> Column:
    """Spark Column expression equal to :func:`node_id`, by column name."""
    from pyspark.sql import functions as F

    return node_id_expr_from_columns(*(F.col(c) for c in column_names))


def value_id_expr() -> Column:
    """Spark Column expression for a Value-node id: ``<col_id>.md5(val)``.

    Built from the column's ``col_id`` (a :func:`node_id`) plus the md5 of the
    value, matching the shared ``generate_value_id`` recipe
    (``compose_id(...).<value-hash>``). Expects the input DataFrame to expose
    ``col_id`` and ``val``, matching the sample-value transform's intermediate
    schema.
    """
    from pyspark.sql import functions as F

    return F.concat(F.col("col_id"), F.lit(_PART_SEP), F.md5(F.col("val")))
