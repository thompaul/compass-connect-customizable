"""
The deploy order and the teardown order must stay the exact reverse of one another.

They had drifted: one module was missing from the teardown entirely, and two others were
ordered inconsistently with the order they are created in — under a comment claiming
reverse-dependency order. The orders are now derived from a single declaration, so this
test guards the derivation rather than two hand-maintained lists.
"""
import ast
import os
import sys

# Both directories are needed: this module's own imports resolve from scripts/, and
# _types reaches into environment/ from the iac root. Without these the file cannot be
# run directly, which for a guard test means it does not get run.
_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_SCRIPTS, '..')))
sys.path.insert(0, _SCRIPTS)

from _types import IaCModules, DEPLOY_ORDER, DESTROY_ORDER

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))


def test_destroy_order_is_the_reverse_of_deploy_order():
    assert DESTROY_ORDER == tuple(reversed(DEPLOY_ORDER))


def test_every_environment_module_is_deployed_and_destroyed():
    """No module may be left out of either order. REALM is not part of an environment."""
    environment_modules = {m for m in IaCModules if m is not IaCModules.REALM}
    assert set(DEPLOY_ORDER) == environment_modules
    assert set(DESTROY_ORDER) == environment_modules


def _names_iterated_by(filename: str, function_name: str) -> set:
    """The names a specific function iterates over with a for loop."""
    with open(os.path.join(_SCRIPTS_DIR, filename), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return {
                child.iter.id
                for child in ast.walk(node)
                if isinstance(child, ast.For) and isinstance(child.iter, ast.Name)
            }
    raise AssertionError(f"{function_name} not found in {filename}")


def test_deploy_iterates_the_declared_order():
    """
    The function that deploys must iterate DEPLOY_ORDER, not a sequence of its own.

    Checked on the function rather than the file: another function in the same file
    iterating the right name would otherwise satisfy the test while the one that
    matters hand-rolled its own list.
    """
    assert "DEPLOY_ORDER" in _names_iterated_by("up.py", "_deploy_environment")


def test_teardown_iterates_the_declared_order():
    assert "DESTROY_ORDER" in _names_iterated_by("destroy.py", "destroy_stack")


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
            print(f"FAIL {_name}: {_e}")
    print(f"\n{'FAILED' if _failed else 'OK'} - {_failed} failed")
    sys.exit(1 if _failed else 0)
