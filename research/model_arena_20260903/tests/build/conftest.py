"""Make the standalone ``build/`` scripts importable as plain modules.

``build/`` is deliberately not a package under ``arena`` (ARENA_CONTRACT
section 6 / the lane brief: "registry_check.py: a script under build/, not a
package under arena"), so it needs its own sys.path entry rather than relying
on the namespace-root conftest.py that makes ``arena`` importable.
"""

from __future__ import annotations

import sys
from pathlib import Path

BUILD_DIR = Path(__file__).resolve().parents[2] / "build"
if str(BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(BUILD_DIR))
