"""Make the repo's ``scripts/`` directory importable for the S0 tooling tests.

``scripts/`` is not a package — the gate/parity scripts run as ``__main__`` with their
own directory on ``sys.path[0]`` (which is how ``check_regression_gate`` resolves its
``from check_marker_parity import ...``). Tests that exercise those modules need the same
directory on ``sys.path`` to import them as top-level modules, so add it here (loaded
before the sibling test modules).
"""

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
