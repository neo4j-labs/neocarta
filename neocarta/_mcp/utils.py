"""Utilities for the MCP server."""

# Characters the Lucene query parser treats as syntax; each is backslash-escaped
# so an untrusted query term is matched literally instead of being interpreted.
_LUCENE_SPECIAL_CHARS = frozenset('+-&|!(){}[]^"~*?:\\/')

# Bare keyword operators Lucene honours only when upper-cased; lower-casing them
# turns them into ordinary search terms (the default full-text analyser lower-cases
# tokens at index time, so matching is unaffected).
_LUCENE_OPERATORS = frozenset({"AND", "OR", "NOT", "TO"})


def escape_lucene_query(text: str | None) -> str | None:
    """Escape a user string so Lucene treats it as literal search terms.

    The MCP full-text/hybrid search tools pass the result as the ``$queryText``
    parameter to ``db.index.fulltext.queryNodes``. Rather than *stripping* special
    characters (which silently drops content such as ``C++`` and leaves the boolean
    operators ``AND``/``OR``/``NOT`` live), this backslash-escapes every Lucene
    special character and lower-cases the bare boolean operators. That neutralises
    Lucene query-syntax injection and avoids parser errors on hostile input, while
    preserving the search terms. Values are passed as a query *parameter*, so there
    is no Cypher-injection surface; this only hardens the Lucene layer.

    Parameters
    ----------
    text : str | None
        The raw, possibly untrusted, search text.

    Returns:
    -------
    str | None
        The escaped query, or ``None`` when the input is empty or blank.
    """
    if not text or not text.strip():
        return None

    escaped_tokens = []
    for token in text.split():
        neutralized = token.lower() if token in _LUCENE_OPERATORS else token
        escaped_tokens.append(
            "".join(f"\\{ch}" if ch in _LUCENE_SPECIAL_CHARS else ch for ch in neutralized)
        )
    return " ".join(escaped_tokens)


def escape_lucene_query_or_error(text: str | None) -> str:
    """Escape ``text`` for Lucene, raising if it has no searchable content.

    Wraps :func:`escape_lucene_query` for the MCP full-text/hybrid search tools,
    which pass the result straight to ``db.index.fulltext.queryNodes`` — a
    procedure whose ``queryString`` argument must be a ``STRING``. Blank or
    whitespace-only ``text_content`` escapes to ``None``; without this guard that
    ``None`` would reach Cypher and surface as an opaque Neo4j type error instead
    of a clear validation message. Raises ``ValueError`` (FastMCP relays the
    message to the client) rather than returning ``None``.

    Parameters
    ----------
    text : str | None
        The raw, possibly untrusted, search text.

    Returns:
    -------
    str
        The escaped, non-empty query.

    Raises:
    ------
    ValueError
        If ``text`` is empty or contains only whitespace / Lucene syntax that
        reduces to nothing searchable.
    """
    query = escape_lucene_query(text)
    if not query:
        raise ValueError(
            "text_content must contain at least one searchable, non-whitespace character."
        )
    return query
