"""Shared, non-collected test support code.

Modules under ``tests.support`` are helper libraries (no ``test_`` prefix), so
pytest does not collect them as tests and the S0-3 marker partition is unaffected.
They are importable as ``from tests.support... import ...`` (``tests`` resolves as a
namespace package, as the existing ``tests.integration._mcp.conftest`` import shows).
"""
