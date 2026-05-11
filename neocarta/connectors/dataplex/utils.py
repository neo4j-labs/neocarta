"""Utility functions for parsing Dataplex resource paths."""


def parse_glossary_resource_path(resource_path: str) -> str:
    """
    Extract the glossary resource path from a Dataplex category or term resource path.

    Parameters
    ----------
    resource_path : str
        Full Dataplex resource path for a category or term, e.g.
        ``projects/.../glossaries/my-glossary/categories/entity-identifiers`` or
        ``projects/.../glossaries/my-glossary/terms/order-item-id``.

    Returns:
    -------
    str
        The glossary resource path, e.g.
        ``projects/.../glossaries/my-glossary``.

    Raises:
    ------
    ValueError
        If the path does not contain a ``glossaries`` segment with a slug following it.
    """
    parts = resource_path.split("/")
    try:
        glossaries_idx = parts.index("glossaries")
    except ValueError:
        raise ValueError(
            f"Expected a Dataplex resource path containing 'glossaries', got: {resource_path!r}"
        ) from None
    if glossaries_idx + 1 >= len(parts):
        raise ValueError(f"Expected 'glossaries/<slug>' in path, got: {resource_path!r}")
    return "/".join(parts[: glossaries_idx + 2])


def parse_category_slug(resource_path: str) -> str:
    """
    Extract the category slug from a Dataplex category resource path.

    Parameters
    ----------
    resource_path : str
        Full Dataplex resource path, e.g.
        ``projects/.../locations/.../glossaries/.../categories/entity-identifiers``.

    Returns:
    -------
    str
        The slug, e.g. ``entity-identifiers``.

    Raises:
    ------
    ValueError
        If the path does not contain a ``categories`` segment immediately before the slug.
    """
    parts = resource_path.split("/")
    if len(parts) < 2 or parts[-2] != "categories":
        raise ValueError(
            f"Expected a Dataplex category resource path (…/categories/<slug>), got: {resource_path!r}"
        )
    return parts[-1]


def parse_business_term_slug(resource_path: str) -> str:
    """
    Extract the business term slug from a Dataplex term resource path.

    Parameters
    ----------
    resource_path : str
        Full Dataplex resource path, e.g.
        ``projects/.../locations/.../glossaries/.../terms/order-item-id``.

    Returns:
    -------
    str
        The slug, e.g. ``order-item-id``.

    Raises:
    ------
    ValueError
        If the path does not contain a ``terms`` segment immediately before the slug.
    """
    parts = resource_path.split("/")
    if len(parts) < 2 or parts[-2] != "terms":
        raise ValueError(
            f"Expected a Dataplex term resource path (…/terms/<slug>), got: {resource_path!r}"
        )
    return parts[-1]
