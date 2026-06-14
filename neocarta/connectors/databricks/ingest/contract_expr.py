"""Graph-contract identifier builders for the Databricks connector.

This module owns the connector's node-identity scheme. It deliberately does NOT
reuse the shared ``neocarta.connectors.utils.generate_id`` helpers: those are
shared by the BigQuery / CSV / Dataplex connectors and use a *lossy*
normalization (lowercase, then space and hyphen both folded to underscore). That
folding is unsafe as a Unity Catalog identity key — see "Why a hash" below — so
this connector builds its own ids here, where the Python and Spark
implementations live side by side and can be kept byte-identical.

Two id forms, two jobs
----------------------
``qualified_name`` — the human-readable, *lossless* dotted path,
``catalog.schema.table.column``, lowercased but otherwise verbatim. Stored as a
node property for debugging and hand-written Cypher. NOT used as the MERGE key.

``node_id`` — ``md5(qualified_name)``: an opaque 32-hex-char digest. This is the
Neo4j MERGE key (the value NODE KEY / uniqueness constraints are enforced
against). It is never parsed apart; the structural parts are carried as their own
node properties (``catalog`` / ``schema`` / ``table``), so the id only ever needs
to be a stable, collision-free key.

Why a hash, and how it avoids data corruption
---------------------------------------------
The MERGE key must be *injective*: two distinct Unity Catalog objects must never
produce the same id, or Neo4j MERGE silently folds them into one node and the
graph is corrupted (the surviving ``name`` is just whichever row wrote last).

The previous scheme folded both spaces and hyphens to ``_`` before joining on
``.``. That is NOT injective: a schema named ``graph-enriched-schema`` and a
schema named ``graph_enriched_schema`` are two distinct, co-existing Unity
Catalog securable objects, yet both folded to the id ``graph_enriched_schema``
and collided.

The fix relies on a Unity Catalog naming guarantee. UC object names (catalog,
schema, table, column) **cannot contain** the period ``.``, the space, the
forward slash, ASCII control characters (0x00-0x1F), or DELETE (0x7F), and UC
stores every object name lowercased. See the SQL identifier rules:
https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-names.html

Two consequences make this scheme correct:

1. Because ``.`` can never appear inside a part, joining the lowercased parts
   with ``.`` is an *unambiguous, reversible* encoding of the
   ``(catalog, schema, table, column)`` tuple: ``(a, b.c)`` is impossible, so it
   can never be confused with ``(a.b, c)``. ``qualified_name`` is therefore an
   injective function of the tuple.
2. ``node_id = md5(qualified_name)`` is then injective up to an md5 collision
   (the same assumption already relied on for Value-node ids). Distinct objects
   get distinct ids; identical objects (UC is case-insensitive, hence the
   lowercase) collapse to one node, which is exactly what we want. Hyphens,
   underscores, and every other legal character survive into the digest input
   unchanged, so ``graph-enriched-schema`` and ``graph_enriched_schema`` now hash
   to different ids and stay separate nodes.

Byte-for-byte Python/Spark agreement
------------------------------------
Ids are produced on the driver (Python: ``node_id`` / ``qualified_name``) and
inside Spark (``node_id_expr`` / ``qualified_name_expr``); both must yield the
identical string for the same input or edges (matched by id) would not connect to
their nodes. Agreement is maintained by construction: both lowercase, both join
with ``.``, both md5 the result, and md5 hex is lowercase 32 chars on both sides.
There is no separate runtime check enforcing it, so keep the two in lockstep when
editing either.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyspark.sql import Column

# The part separator. Safe as a delimiter precisely because Unity Catalog forbids
# it inside any object name (see module docstring), so the dotted join is an
# injective encoding of the identifier tuple.
_PART_SEP = "."


def qualified_name(*parts: str) -> str:
    """Return the lossless, lowercased dotted path for an identifier tuple.

    ``catalog.schema.table.column`` (or any prefix), lowercased to match Unity
    Catalog's lowercase storage but otherwise verbatim — hyphens and other legal
    characters are preserved. This is a node property and the input to
    :func:`node_id`; it is never the MERGE key itself.

    Examples:
    --------
    >>> qualified_name("my-catalog", "sales", "orders")
    'my-catalog.sales.orders'
    """
    return _PART_SEP.join(p.lower() for p in parts)


def node_id(*parts: str) -> str:
    """Return the opaque MERGE key for an identifier tuple: ``md5(qualified_name)``.

    Collision-free across distinct Unity Catalog objects (modulo md5), because
    :func:`qualified_name` is an injective encoding of the tuple. See the module
    docstring for why this matters.

    Examples:
    --------
    >>> node_id("my-catalog", "sales", "orders")
    '8f9e5e6d...'  # doctest: +SKIP
    """
    return hashlib.md5(qualified_name(*parts).encode(), usedforsecurity=False).hexdigest()


def qualified_name_expr_from_columns(*parts: Column) -> Column:
    """Spark Column expression equal to :func:`qualified_name`.

    Accepts arbitrary Column expressions, including literals. ``lower`` after
    ``concat_ws('.')`` is identical to lowercasing each part then joining, since
    the ``.`` separator is unaffected by ``lower`` — keeping it byte-identical to
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

    Accepts arbitrary Column expressions, including literals. Use this when an
    identifier combines Python-known values with Spark row values.
    """
    from pyspark.sql import functions as F

    return F.md5(qualified_name_expr_from_columns(*parts))


def node_id_expr(*column_names: str) -> Column:
    """Spark Column expression equal to :func:`node_id`, by column name."""
    from pyspark.sql import functions as F

    return node_id_expr_from_columns(*(F.col(c) for c in column_names))


def value_id_expr() -> Column:
    """Spark Column expression for a Value-node id: ``<col_id>.md5(val)``.

    Built from the column's already-hashed ``col_id`` plus the md5 of the value,
    so it is collision-free whenever ``col_id`` is (it is — ``col_id`` is a
    :func:`node_id`). The ``.`` join is unambiguous because an md5 digest never
    contains ``.``. Expects the input DataFrame to expose ``col_id`` and ``val``,
    matching the sample-value transform's intermediate schema.
    """
    from pyspark.sql import functions as F

    return F.concat(F.col("col_id"), F.lit(_PART_SEP), F.md5(F.col("val")))
