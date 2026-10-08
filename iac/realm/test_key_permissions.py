#!/usr/bin/env python3
"""
An exported service account key must be readable only by its owner.

These are live credentials to the realm's cloud with CI/CD rights over every environment
in it. They were written with a plain `open(path, "w")`, which takes the process umask and
on a normal machine leaves them at 0644 - world-readable, on a laptop or a build agent,
for as long as they exist.

Runnable directly: `python3 realm/test_key_permissions.py` from the iac directory.
"""
import os
import stat
import sys
import tempfile

# Both directories: this module's own imports resolve from realm/, and create_realm
# reaches into lib from the iac root. Without these the file cannot be run directly,
# which for a guard test means it does not get run.
_REALM = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_REALM, "..")))
sys.path.insert(0, _REALM)

from create_realm import write_private_key  # noqa: E402

KEY = '{"type": "service_account", "private_key": "-- not a real key --"}'


def _mode(path: str) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def test_a_new_key_is_owner_only():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "realm-upper-env-ci-cd-key.json")
        write_private_key(path, KEY)
        assert _mode(path) == 0o600, f"written as {oct(_mode(path))}, not 0600"
        assert open(path).read() == KEY


def test_the_umask_cannot_widen_it():
    """A permissive umask is exactly the machine where this matters."""
    previous = os.umask(0o000)
    try:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "key.json")
            write_private_key(path, KEY)
            assert _mode(path) == 0o600, f"written as {oct(_mode(path))} under umask 000"
    finally:
        os.umask(previous)


def test_re_exporting_over_a_world_readable_key_narrows_it():
    """
    The case the open mode alone does not cover.

    O_CREAT's mode applies only to a file that did not exist, so a realm re-exported over
    keys an earlier run left at 0644 would have kept them there - and a rebuild is exactly
    when nobody looks.
    """
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "key.json")
        with open(path, "w") as existing:
            existing.write("an older key")
        os.chmod(path, 0o644)

        write_private_key(path, KEY)
        assert _mode(path) == 0o600, f"left at {oct(_mode(path))} after re-export"
        assert open(path).read() == KEY


def test_nothing_readable_is_left_behind_if_the_write_fails():
    """A partial key is still a key; a failed export must not leave a readable one."""
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "key.json")
        with open(path, "w") as existing:
            existing.write(KEY)
        os.chmod(path, 0o644)
        try:
            write_private_key(path, None)  # type: ignore[arg-type]
        except TypeError:
            pass
        assert _mode(path) == 0o600, f"left at {oct(_mode(path))} after a failed write"
        assert open(path).read() == "", "the previous key survived a failed re-export"


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
