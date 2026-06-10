"""Central logging configuration and helpers for the neocarta package.

Importing neocarta as a library is silent: the package root logger carries a
:class:`logging.NullHandler` (attached in :mod:`neocarta`) and nothing else.
Only a host that opts in — chiefly the CLI — calls :func:`configure_logging`
to attach a real handler.

The package uses a per-module logger hierarchy: every module calls
``logging.getLogger(__name__)`` (e.g. ``neocarta.connectors.bigquery.schema.extract``,
``neocarta.ingest.rdbms.load``), all of which descend from the ``neocarta`` root
logger configured here. :data:`PACKAGE_LOGGER_NAME` is that root.

Two instrumentation helpers are provided for connector code:

- :func:`log_stage` — a decorator for extractor methods that logs a one-line
  summary (target + row count + elapsed) at INFO. It never logs SQL or row
  values; only the return-value count and an allowlist of safe scalar kwargs.
- :func:`log_timing` — a context-manager escape hatch for code paths that do
  not fit the decorator (e.g. early-return branches).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from contextlib import contextmanager
from functools import wraps
from typing import TYPE_CHECKING, Any, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

    from rich.console import Console

PACKAGE_LOGGER_NAME = "neocarta"

F = TypeVar("F", bound=Callable[..., Any])

# Sentinel marking handlers this module owns, so configure_logging can replace
# its own handler idempotently without disturbing a NullHandler or handlers a
# host application attached.
_MANAGED_ATTR = "_neocarta_managed"

# Allowlist of keyword-argument names that are safe to surface as the logged
# "target" of an extractor call. These name *what* was fetched (a dataset,
# table, file, or model) — never row values or query text. Do NOT add keys
# that can carry data values or SQL (e.g. ``column_names``, ``query``).
_SAFE_TARGET_KEYS: tuple[str, ...] = (
    "dataset_id",
    "table_name",
    "region",
    "filename",
    "spec_source",
    "semantic_model_name",
    "name",
)


def configure_logging(
    level: int | str = logging.INFO,
    *,
    console: Console | None = None,
) -> logging.Logger:
    """
    Configure the ``neocarta`` package root logger.

    Idempotent: any handler previously attached by this function is removed
    before a new one is added, so repeated calls (tests, nested invocations)
    never duplicate output. ``propagate`` is left at its default (``True``) so
    that pytest's ``caplog`` fixture — which captures via the root logger —
    keeps working in code paths that do not call this function.

    Parameters
    ----------
    level : int or str
        Logging level applied to the ``neocarta`` logger and its handler,
        e.g. :data:`logging.DEBUG` or ``"DEBUG"``.
    console : rich.console.Console, optional
        The CLI's stderr Rich console. When provided, records render through it
        via :class:`rich.logging.RichHandler`, inheriting its color system (so
        ``--no-color`` is honored automatically). When omitted, a plain
        :class:`logging.StreamHandler` to ``stderr`` is used.

    Returns:
    -------
    logging.Logger
        The configured ``neocarta`` logger.
    """
    logger = logging.getLogger(PACKAGE_LOGGER_NAME)
    logger.setLevel(level)

    for existing in list(logger.handlers):
        if getattr(existing, _MANAGED_ATTR, False):
            logger.removeHandler(existing)
            existing.close()

    handler: logging.Handler
    if console is not None:
        # Local import keeps rich off the library import path.
        from rich.logging import RichHandler  # noqa: PLC0415

        handler = RichHandler(
            console=console,
            show_path=False,
            show_time=True,
            show_level=True,
            rich_tracebacks=True,
            # Pattern strings such as "(:Column)-[:TAGGED_WITH]->(:BusinessTerm)"
            # contain "[:...]"; markup parsing would mangle them.
            markup=False,
        )
    else:
        handler = logging.StreamHandler()  # defaults to sys.stderr

    handler.setLevel(level)
    setattr(handler, _MANAGED_ATTR, True)
    logger.addHandler(handler)
    return logger


def humanize(method_name: str) -> str:
    """
    Turn a snake_case method name into a human-readable label.

    Examples:
    --------
    >>> humanize("extract_table_info")
    'Extract table info'
    """
    return method_name.replace("_", " ").strip().capitalize()


def log_transform_counts(
    logger: logging.Logger,
    source: Any,
    fields: Iterable[tuple[str, str]],
) -> None:
    """
    Log per-type produced-object counts read off ``source``.

    For each ``(label, attr)`` pair, logs ``"Transformed N <label>"`` at INFO
    when ``len(getattr(source, attr))`` is non-zero; zero-count types are
    skipped so an empty phase stays quiet. Connectors define the ``fields``
    sequence (which node/relationship lists to report, in order); this shared
    helper owns the loop so the logging shape stays consistent across them.

    Parameters
    ----------
    logger : logging.Logger
        The connector module's logger.
    source : object
        The transformer holding the produced lists (e.g. ``self.transformer``).
    fields : iterable of (str, str)
        ``(human_label, attribute_name)`` pairs to count and report.
    """
    if not logger.isEnabledFor(logging.INFO):
        return
    for label, attr in fields:
        produced = len(getattr(source, attr))
        if produced:
            logger.info("Transformed %d %s", produced, label)


def _row_count(result: Any) -> int | None:
    """
    Best-effort row count for an extractor return value.

    Returns ``len`` for a pandas ``DataFrame`` (duck-typed via ``shape``) or a
    list, the summed length for a ``dict`` of such values (an extractor that
    pulls several frames at once reports the total rows pulled), and ``None``
    when no meaningful count exists (e.g. a parsed OSI spec dict or ``None``).

    Note that summing a ``dict`` only makes sense when its frames are the same
    kind of thing. An extractor whose mapping mixes heterogeneous or derived
    frames (e.g. queries plus the tables/columns parsed out of them) should
    opt out with ``count=False`` on :func:`log_stage` rather than emit a
    meaningless sum.
    """
    if result is None:
        return None
    # pandas DataFrame / Series — duck-typed to avoid importing pandas here.
    shape = getattr(result, "shape", None)
    if shape is not None:
        try:
            return int(shape[0])
        except (TypeError, IndexError):
            return None
    if isinstance(result, dict):
        total = 0
        counted = False
        for value in result.values():
            value_shape = getattr(value, "shape", None)
            if value_shape is not None:
                total += int(value_shape[0])
                counted = True
            elif isinstance(value, list):
                total += len(value)
                counted = True
        return total if counted else None
    if isinstance(result, list):
        return len(result)
    return None


def _safe_target(kwargs: Mapping[str, Any]) -> str | None:
    """
    Build a target string from allowlisted, scalar keyword arguments.

    Only names in :data:`_SAFE_TARGET_KEYS` whose values are ``str``/``int`` are
    included, so no row values or query text can leak into the log line.
    """
    parts = [
        f"{key}={kwargs[key]}"
        for key in _SAFE_TARGET_KEYS
        if isinstance(kwargs.get(key), (str, int))
    ]
    return ", ".join(parts) if parts else None


def log_stage(func: F | None = None, *, count: bool = True) -> F | Callable[[F], F]:
    """
    Decorate an extractor method to log a one-line execution summary at INFO.

    The wrapped method's module determines the logger
    (``logging.getLogger(func.__module__)``), giving the per-module hierarchy
    for free. The summary contains the humanized method name, an optional
    target (allowlisted scalar kwargs only), an optional row count derived from
    the return value, and the elapsed wall-clock time. SQL is a method-local
    and never crosses this boundary, so it is never logged.

    Parameters
    ----------
    func : callable, optional
        The method being decorated (supplied automatically when used without
        parentheses).
    count : bool, default True
        When False, the row count is omitted (for extractors whose return value
        has no meaningful row count, e.g. OSI spec/snapshot dicts).
    """

    def decorate(fn: F) -> F:
        logger = logging.getLogger(fn.__module__)

        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            result = fn(*args, **kwargs)
            elapsed = time.perf_counter() - start
            if logger.isEnabledFor(logging.INFO):
                parts = [humanize(fn.__name__)]
                target = _safe_target(kwargs)
                if target:
                    parts.append(target)
                if count:
                    rows = _row_count(result)
                    if rows is not None:
                        parts.append(f"{rows} rows")
                parts.append(f"{elapsed:.1f}s")
                logger.info("%s", " — ".join(parts))
            return result

        return cast("F", wrapper)

    if func is not None:
        return decorate(func)
    return decorate


@contextmanager
def log_timing(
    logger: logging.Logger,
    label: str,
    *,
    target: str | None = None,
) -> Iterator[None]:
    """
    Context manager that logs ``label`` (and optional ``target``) with elapsed
    time at INFO when the block completes.

    Use this where :func:`log_stage` does not fit — for example a private helper
    with early-return branches that want to log distinct outcomes.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        if target:
            logger.info("%s — %s — %.1fs", label, target, elapsed)
        else:
            logger.info("%s — %.1fs", label, elapsed)
