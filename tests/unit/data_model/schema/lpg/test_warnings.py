"""Unit tests for LPG data model import warnings."""

import importlib

import pytest

import neocarta.data_model.schema.lpg as lpg_module


def test_lpg_import_triggers_warning():
    """Importing LPG data model components should emit an in-progress warning."""
    with pytest.warns(UserWarning, match="LPG data model"):
        importlib.reload(lpg_module)
