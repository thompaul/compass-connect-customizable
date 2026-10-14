#!/usr/bin/env python3
"""
Nobody chose the numbers that decided whether this service could start.

Cloud Run's default startup probe is a single TCP check with a failure threshold of one, so a
container had 240 seconds to open its port and one chance to do it. PyMongo's default
server-selection timeout is 30 seconds, so the application gave up after 30 of those 240 and
exited. Cloud Run destroyed the instance, waited, and started another - which succeeded, with
the same image, the same credentials and the same access list as the one it had just killed.
The user paid 1m59s for a retry the process could have done itself in a quarter of a second.

Both numbers are now declared. These tests pin the relationship between them, because the
failure they are there to prevent is not either number being wrong on its own - it is the
platform's budget quietly falling below the application's, so that the container is killed
before it can finish saying which database it could not reach and why.

Read from the source rather than by importing it: `deploy_backend` imports pulumi, and a
guard that only runs where pulumi is installed is a guard that does not run.

Runnable directly: `python3 backend/test_startup_budget.py` from the iac directory.
"""
import ast
import os
import sys

_SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy_backend.py")
_TREE = ast.parse(open(_SOURCE).read())


def _constants() -> dict:
    """The module-level integers, without executing a module that needs pulumi."""
    found = {}
    for node in _TREE.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(node.value.value, int):
                    found[target.id] = node.value.value
    return found


def _startup_probe() -> dict:
    """The keyword arguments the service's startup probe is built with."""
    for call in ast.walk(_TREE):
        if not isinstance(call, ast.Call):
            continue
        for keyword in call.keywords:
            if keyword.arg == "startup_probe" and isinstance(keyword.value, ast.Call):
                return {k.arg: ast.unparse(k.value) for k in keyword.value.keywords}
    raise AssertionError(
        "no startup_probe is declared, so Cloud Run's default applies: one TCP check, "
        "failure threshold one, and a container that misses it is destroyed")


def test_the_probe_is_declared_rather_than_inherited():
    probe = _startup_probe()
    for setting in ("period_seconds", "timeout_seconds", "failure_threshold"):
        assert setting in probe, f"{setting} is left to the platform's default"
    assert "tcp_socket" in probe or "http_get" in probe, "the probe checks nothing"


def test_the_probe_asks_more_than_once():
    """
    The whole difference between the old behaviour and the new one.

    One strike means a container that is waiting on a dependency is destroyed rather than
    waited for, and the retry is paid for in instances and in the platform's own backoff.
    """
    constants = _constants()
    threshold = constants[_startup_probe()["failure_threshold"]]
    assert threshold > 1, (
        f"the probe gives up after {threshold} failure(s), which is the default it replaced")


def test_the_application_reaches_its_own_limit_before_the_platform_does():
    """
    Whatever goes wrong, the application must be the thing that gives up, because it is the
    only one of the two that knows which database it was and why it would not answer. The
    platform can only report that a probe timed out.

    Container boot and Python import take about 7 seconds before the first ping, measured on
    a successful cold start, so the margin is not decoration.
    """
    constants = _constants()
    probe = _startup_probe()
    platform = constants[probe["period_seconds"]] * constants[probe["failure_threshold"]]
    application = constants["DATABASE_STARTUP_BUDGET_SECONDS"]

    assert application < platform, (
        f"the application retries for {application}s inside a {platform}s allowance, so the "
        f"platform kills it first and the diagnosis is lost")
    assert platform - application >= 60, (
        f"only {platform - application}s separates them, which a slow image pull or a cold "
        f"interpreter can use up on its own")


def test_the_budget_reaches_the_application_that_spends_it():
    """
    A number declared here and defaulted there is two numbers. The container is told what it
    is, so that changing it in one place changes it.
    """
    source = open(_SOURCE).read()
    assert "BACKEND_DATABASE_STARTUP_BUDGET_SECONDS" in source, (
        "the budget is not passed to the container, so the application falls back to its own "
        "default and the two drift apart silently")
    assert "str(DATABASE_STARTUP_BUDGET_SECONDS)" in source, (
        "the value passed to the container is not the constant declared beside the probe")

    backend = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "backend", "common_libs", "database", "utils.py")
    assert 'STARTUP_BUDGET_VARIABLE = "BACKEND_DATABASE_STARTUP_BUDGET_SECONDS"' in \
        open(backend).read(), (
        "the application reads a different variable than the deployment sets, so the budget "
        "is set by nobody and defaults on both sides")


def test_the_probe_watches_the_port_the_container_listens_on():
    """A probe aimed at a port nothing is bound to fails for the whole budget and then
    reports only that it timed out."""
    constants = _constants()
    probe = _startup_probe()
    if "tcp_socket" not in probe:
        return
    assert "CONTAINER_PORT" in probe["tcp_socket"], (
        "the probe's port is written out rather than named, so it can stop matching the port "
        "in the Dockerfile without anything noticing")

    dockerfile = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "backend", "Dockerfile")
    assert f"--port {constants['CONTAINER_PORT']}" in open(dockerfile).read(), (
        f"the container binds a different port than {constants['CONTAINER_PORT']}")


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
        except Exception as _e:  # noqa: BLE001 - a test that raises is a test that failed
            _failed += 1
            print(f"FAIL {_name}: raised {type(_e).__name__}: {_e}")
    print(f"\n{'FAILED' if _failed else 'OK'} - {_failed} failed")
    sys.exit(1 if _failed else 0)
