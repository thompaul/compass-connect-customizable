#!/usr/bin/env python3
"""
Things that make the product's own pipeline fail, checked without running it.

This branch ran its own tests constantly and never ran the product's CI, so it accumulated
failures nobody saw: a security scanner flagging a test fixture, a formatter rejecting five
files, a linter rejecting two warnings, and a test file whose name stopped pytest collecting
anything at all. Each was found by pushing and waiting fifteen minutes.

These are the ones that can be checked from the source in a second.

Runnable directly: `python3 test_ci_preconditions.py` from the iac directory.
"""
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKEND = os.path.join(_REPO, "backend")


def _test_files(root: str):
    for directory, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith((".", "venv")) and d != "node_modules"]
        for name in files:
            if name.startswith("test_") and name.endswith(".py"):
                yield directory, name


def test_no_two_rootless_test_files_share_a_name():
    """
    pytest imports a test file by its basename unless its directory is a package. Two files
    called `test_utils.py` in directories without `__init__.py` are the same module name, and
    pytest stops with a collection error — not a failing test, a refusal to collect anything:

        ERROR common_libs/database/test_utils.py
        Interrupted: 1 error during collection
        964 deselected, 1 error

    The backend has three `test_utils.py`. Two are inside packages and are fine. A fourth,
    added by this work outside a package, took the whole suite down.
    """
    rootless = {}
    for directory, name in _test_files(_BACKEND):
        if os.path.exists(os.path.join(directory, "__init__.py")):
            continue
        rootless.setdefault(name, []).append(os.path.relpath(directory, _REPO))

    clashes = {name: dirs for name, dirs in rootless.items() if len(dirs) > 1}
    assert not clashes, (
        "two test files share a name and neither directory is a package, so pytest collects "
        "neither:\n"
        + "\n".join(f"    {name}  in  {', '.join(dirs)}" for name, dirs in sorted(clashes.items()))
        + "\nRename one, or add __init__.py to its directory.")


def test_the_invented_credential_in_the_database_tests_is_marked():
    """
    Bandit reads `PASSWORD = "..."` as a hardcoded credential and fails the build. That string
    is invented and is the point of those tests — they assert it never reaches a log line,
    which needs it to be a literal. The marker is what tells the scanner so.
    """
    path = os.path.join(_BACKEND, "common_libs", "database", "test_database_utils.py")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        if line.startswith(("PASSWORD =", "URI =")):
            assert "nosec" in line, (
                f"a literal credential in the database tests is unmarked, so bandit fails the "
                f"build:\n    {line.strip()}")


if __name__ == "__main__":
    _failed = 0
    for _name, _test in sorted(globals().items()):
        if not _name.startswith("test_") or not callable(_test):
            continue
        try:
            _test()
            print(f"ok   {_name}")
        except AssertionError as _e:
            _failed += 1
            print(f"FAIL {_name}:\n  {_e}")
        except Exception as _e:  # noqa: BLE001
            _failed += 1
            print(f"FAIL {_name}: raised {type(_e).__name__}: {_e}")
    print(f"\n{'FAILED' if _failed else 'OK'} - {_failed} failed")
    sys.exit(1 if _failed else 0)
