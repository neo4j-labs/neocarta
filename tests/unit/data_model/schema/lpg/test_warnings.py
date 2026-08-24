"""Unit tests for LPG data model imports."""

import importlib
import warnings

import neocarta.data_model.schema.lpg as lpg_module


def test_importing_lpg_models_does_not_warn():
    """Importing LPG data model components must not emit a warning.

    The LPG components now have a consumer (the Neo4j connector / LPG ingest path),
    so the previous "in-progress" warning has been removed.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        importlib.reload(lpg_module)  # force re-execution of module-level code
