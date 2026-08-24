"""Translate neo4j driver exceptions into neocarta typed errors.

The neo4j driver is a hard dependency with its own ``neo4j.exceptions`` hierarchy
(not PEP-249 DB-API), so -- like the BigQuery connector -- this classifies against
that hierarchy directly and does NOT use ``connectors/utils/dbapi_errors.py``.
Exceptions that are not neo4j driver exceptions are re-raised untouched so local
bugs are never masked. Only the exception class drives classification; message text
is never inspected.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, TypeVar

from neo4j.exceptions import AuthError as Neo4jAuthError
from neo4j.exceptions import ClientError, Forbidden, Neo4jError, ServiceUnavailable

from ...errors import AuthError, ExtractionError, Neo4jConnectionError

if TYPE_CHECKING:
    from collections.abc import Callable

_R = TypeVar("_R")


def wrap_neo4j_errors(func: Callable[..., _R]) -> Callable[..., _R]:
    """Wrap a source-read method, mapping neo4j driver errors to neocarta errors.

    Args:
        func: The method to wrap.

    Returns:
        The wrapped method.
    """

    @functools.wraps(func)
    def wrapper(*args: object, **kwargs: object) -> _R:
        try:
            return func(*args, **kwargs)
        except ServiceUnavailable as exc:
            raise Neo4jConnectionError(
                "Could not reach the source Neo4j instance.",
                suggestion="Check the source URI, network, and that the instance is running.",
            ) from exc
        except Neo4jAuthError as exc:  # subclass of ClientError -- catch first
            raise AuthError(
                "Authentication with the source Neo4j instance failed.",
                suggestion="Check the source credentials.",
            ) from exc
        except (Forbidden, ClientError) as exc:
            raise ExtractionError(
                "A schema query against the source Neo4j instance failed.",
                suggestion="Ensure the source role can run apoc.meta.schema().",
            ) from exc
        except Neo4jError as exc:  # any other driver error
            raise ExtractionError(
                "A schema query against the source Neo4j instance failed."
            ) from exc

    return wrapper
