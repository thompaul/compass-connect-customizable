#!/usr/bin/env python3
"""
A database the server refuses to start without must be one something actually reads.

`JOBS_MONGODB_URI` was mandatory. The server raised at import if it was unset, opened a
connection to it at startup and closed it at shutdown — and nothing in between read it.
Compass had stopped owning a jobs collection some time earlier; `app/jobs/routes.py` says
so in its own comment, *"it no longer owns one"*. The requirement outlived the thing it was
for, so every partner provisioned a Mongo database that was never queried, and the runbook
told them to: *"provision them even if you are not using those modules yet."*

That is a specific cost — an Atlas database, a connection string in a secret, a line in
everyone's configuration — paid by every deployment, for nothing. It is also invisible from
either end: the startup check does not know what reads the database, and the code that
stopped reading it had no reason to look at the startup check.

These tests are the comparison neither end could make.

Runnable directly: `python3 test_required_databases.py` from the iac directory.
"""
import ast
import os
import re
import sys

_IAC = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_IAC)

SERVER = os.path.join(_REPO, "backend", "app", "server.py")
BACKEND_APP = os.path.join(_REPO, "backend", "app")

#: Where the databases are opened and handed out. A reference here is plumbing, not a reader:
#: these two files are what the startup check and the provider are made of.
NOT_READERS = {
    os.path.join("backend", "app", "server.py"),
    os.path.join("backend", "app", "server_dependencies", "db_dependencies.py"),
}

#: Databases required for something other than a module reading them. Each needs a reason.
REQUIRED_WITHOUT_A_READER = {}


def required_database_prefixes() -> dict:
    """
    The databases the server refuses to start without, from the checks that do the refusing.

    Read from `if not os.getenv("X_MONGODB_URI"): raise` rather than by matching text, so a
    requirement expressed some other way is absent here — which is honest, since this test
    cannot see it.
    """
    tree = ast.parse(open(SERVER, encoding="utf-8").read())
    required = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if not any(isinstance(statement, ast.Raise) for statement in node.body):
            continue
        for call in ast.walk(node.test):
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "getenv" and call.args
                    and isinstance(call.args[0], ast.Constant)
                    and isinstance(call.args[0].value, str)
                    and call.args[0].value.endswith("_MONGODB_URI")):
                name = call.args[0].value
                required[name[: -len("_MONGODB_URI")].lower()] = name
    return required


def databases_opened_at_startup() -> set:
    """The databases `lifespan` connects to when the process starts."""
    source = open(SERVER, encoding="utf-8").read()
    return set(re.findall(r"CompassDBProvider\.get_([a-z_]+)_db\(\)", source))


def database_readers() -> dict:
    """Every database getter referenced outside the provider and the server, to one file."""
    readers = {}
    for directory, subdirectories, files in os.walk(BACKEND_APP):
        subdirectories[:] = [d for d in subdirectories if d != "__pycache__"]
        for filename in files:
            if (not filename.endswith(".py") or filename.startswith("test_")
                    or filename.endswith("_test.py")):
                continue
            path = os.path.join(directory, filename)
            relative = os.path.relpath(path, _REPO)
            if relative in NOT_READERS:
                continue
            try:
                source = open(path, encoding="utf-8").read()
            except UnicodeDecodeError:
                continue
            for name in re.findall(r"get_([a-z_]+)_db\b", source):
                readers.setdefault(name, relative)
    return readers


def test_every_database_the_server_demands_is_one_something_reads():
    """
    The invariant that was broken, stated so it cannot break again quietly.

    Requiring a database nobody queries is not a harmless extra line: it is an Atlas
    database, a connection string in a secret and a configuration entry, for every
    deployment, forever, until somebody thinks to check.
    """
    required = required_database_prefixes()
    readers = database_readers()
    unread = sorted(prefix for prefix in required
                    if prefix not in readers and prefix not in REQUIRED_WITHOUT_A_READER)
    assert not unread, (
        "the server refuses to start without these and nothing reads them:\n"
        + "\n".join(f"    {required[p]}" for p in unread)
        + "\nDrop the requirement, or record why it stands in REQUIRED_WITHOUT_A_READER.")


def test_nothing_is_connected_at_startup_that_is_not_required():
    """
    The other direction: a connection opened without a matching requirement.

    `get_x_db` on an unset URI does not fail cleanly — it builds a client from an empty
    string — so an optional database opened at startup fails in the driver rather than in
    a message naming the variable.
    """
    required = required_database_prefixes()
    opened = databases_opened_at_startup()
    unrequired = sorted(opened - set(required))
    assert not unrequired, (
        "these are connected at startup and not required: " + ", ".join(unrequired)
        + "\nEither require them, or do not open them where an unset value cannot be reported.")


def test_the_retired_jobs_database_is_not_demanded_again():
    """The instance, kept beside the class: this is the one that was actually wrong."""
    assert "jobs" not in required_database_prefixes(), (
        "JOBS_MONGODB_URI is mandatory again. Compass does not own a jobs collection; the "
        "matching service is the source.")
    assert "jobs" not in databases_opened_at_startup(), (
        "the jobs database is connected at startup again, and nothing reads it.")


def test_the_exception_list_has_no_stale_entries():
    """An exemption that no longer applies is an exemption nobody will re-examine."""
    required = required_database_prefixes()
    readers = database_readers()
    stale = sorted(prefix for prefix in REQUIRED_WITHOUT_A_READER
                   if prefix not in required or prefix in readers)
    assert not stale, ("REQUIRED_WITHOUT_A_READER lists databases that are no longer "
                       "required, or that are now read: " + ", ".join(stale))


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
        except BaseException as _e:  # noqa: BLE001 - a test that raises is a test that failed
            _failed += 1
            print(f"FAIL {_name}: raised {type(_e).__name__}: {_e}")
    print(f"\n{'FAILED' if _failed else 'OK'} - {_failed} failed")
    sys.exit(1 if _failed else 0)
