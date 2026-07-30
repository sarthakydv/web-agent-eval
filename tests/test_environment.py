"""Environment invariants.

These exist so ./init.sh cannot pass vacuously. The predecessor project shipped
four scripts that had never been typechecked, and its test command was passing
on zero test files. A green check that verifies nothing is worse than no check,
because it is trusted.
"""

import sys


def test_python_is_pinned_to_312():
    """3.14 is the system interpreter and is deliberately not used here.

    agisdk allows >=3.9, but pulls numpy/gymnasium/ray/lxml, which lag new
    interpreter releases. See docs/DECISIONS.md entry 2.
    """
    assert sys.version_info[:2] == (3, 12), (
        f"expected Python 3.12, got {sys.version_info.major}.{sys.version_info.minor}"
    )


def test_agisdk_imports_and_exposes_the_real_harness():
    from agisdk import REAL

    assert callable(REAL.harness), "REAL.harness is the entry point every feature builds on"


def test_api_key_is_present_but_never_committed():
    """The key must exist locally and must not be tracked by git."""
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    assert (root / ".env").exists(), ".env missing — copy ZAI_API_KEY into it"

    tracked = subprocess.run(
        ["git", "ls-files", ".env"], cwd=root, capture_output=True, text=True, check=False
    ).stdout.strip()
    assert tracked == "", f".env is TRACKED BY GIT: {tracked!r}"
