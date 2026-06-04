"""The catalog-list policy rule shared by the ingest and query layers.

``resolve_catalogs`` is the single source of truth for "which catalogs does
this run touch". Both ``SparkIngestSettings`` and ``ClientSettings`` resolve
their catalog set through it, so the ingest side and the query side can never
disagree about the ``catalog:layer`` list form.
"""

from __future__ import annotations

from dbxcarta.core.identifiers import validate_identifier


def resolve_catalogs(catalog: str, catalogs: str) -> list[str]:
    """Catalogs to ingest, order-preserving and de-duplicated.

    The single source of truth for "which catalogs does this run touch".
    Both the readiness check and the pipeline resolve their catalog set
    through this one function, so they can never disagree.

    Each entry in ``catalogs`` is ``catalog`` or ``catalog:layer``; the
    ``:layer`` suffix is stripped here. A blank list falls back to the single
    ``catalog``, preserving the historical single-catalog behavior. Duplicates
    are collapsed: a repeated catalog would otherwise double-count extract
    totals and re-write every node. Every resolved name is validated with the
    same rule the pipeline uses, so a malformed catalog fails loud wherever the
    list is resolved.
    """
    listed: list[str] = []
    for part in catalogs.split(","):
        name = part.split(":", 1)[0].strip()
        if name:
            listed.append(name)
    resolved = list(dict.fromkeys(listed)) or [catalog]
    for name in resolved:
        validate_identifier(name, label="catalog")
    return resolved
