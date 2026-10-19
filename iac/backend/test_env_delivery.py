#!/usr/bin/env python3
"""
Everything the operator is asked to set must actually reach the container.

`GLOBAL_DISABLE_REGISTRATION_CODE` was in `env.template`, read by the application,
honoured by its invitation-code validator — and absent from the 53 environment variables
the IaC puts on the Cloud Run service. It had been inert in every deployment that set it.
The frontend build *did* receive it, so the registration form hid the invitation-code
field while the backend went on demanding one, and nothing in the deployment or the
container logs said so.

The variable was the symptom. The cause is that the container's environment is a
hand-written list, derived from nothing and compared with nothing, so a variable added to
the template reaches the backend only if someone remembers this file too. These tests are
that comparison, and they are written against the class of fault rather than the one
instance of it.

Runnable directly: `python3 backend/test_env_delivery.py` from the iac directory.
"""
import ast
import os
import sys

_IAC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.dirname(_IAC)

DEPLOY_BACKEND = os.path.join(_IAC, "backend", "deploy_backend.py")
ENV_TEMPLATE = os.path.join(_IAC, "templates", "env.template")

#: Where the running service reads its configuration. `backend/scripts` is deliberately
#: out: those are run by hand against a deployment, not inside the container, and their
#: variables are nobody's deployment configuration.
BACKEND_SOURCE_ROOTS = ("backend/app", "backend/common_libs", "backend/features")

#: Variables the application reads that the deployment deliberately does not deliver.
#: Each one needs a reason, because the default has to be that an unreachable setting is
#: a defect: the application offers a knob that no deployment can turn.
UNDELIVERED_BY_DESIGN = {
    "LOG_CONFIG_FILE": "selects a logging config file inside the image; the container default is the right one",
    "LLM_MODEL_NAME": "retired, read only to warn that it is now ignored",
    "LOCAL_LLM_THINK": "local Ollama development only",
    "OLLAMA_BASE_URL": "local Ollama development only; a hosted deployment uses a managed provider",
    "ADMIN_FIREBASE_PROJECT_ID": "an admin Firebase project separate from the backend's own is not yet a "
                                 "supported deployment shape - see the note in app/admin/firebase.py",
    "ADAPTIVE_D_EFFICIENCY_ENABLED": "experimental preference-elicitation tuning, not deployment configuration",
    "ADAPTIVE_FIM_THRESHOLD": "experimental preference-elicitation tuning, not deployment configuration",
    "ADAPTIVE_MAX_VIGNETTES": "experimental preference-elicitation tuning, not deployment configuration",
    "ADAPTIVE_MIN_VIGNETTES": "experimental preference-elicitation tuning, not deployment configuration",
    "ADAPTIVE_TEMPERATURE": "experimental preference-elicitation tuning, not deployment configuration",
    "ADAPTIVE_UNCERTAINTY_THRESHOLD": "experimental preference-elicitation tuning, not deployment configuration",
    "ADAPTIVE_VARIANCE_THRESHOLD": "experimental preference-elicitation tuning, not deployment configuration",
    # The two below are read only when INGRESS_MODE is "direct", which is the on-premise shape:
    # the backend verifies Firebase ID tokens and API keys itself because there is no gateway in
    # front of it. A cloud deployment runs in "gateway" mode, the default, where the Google API
    # Gateway does that verification and `validate_ingress_config` returns before either is
    # read. Delivering them would be configuring a code path this deployment shape never enters.
    "FIREBASE_PROJECT_ID": "only read when INGRESS_MODE is 'direct' (on-premise); a cloud "
                           "deployment runs behind the API Gateway, which verifies tokens itself",
    "API_KEYS": "only read when INGRESS_MODE is 'direct' (on-premise); a cloud deployment runs "
                "behind the API Gateway, which verifies API keys itself",
}


def _env_names_read_by(path: str) -> set:
    """Every environment variable one module reads, by literal name."""
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except (SyntaxError, UnicodeDecodeError):
        return set()

    names = set()
    for node in ast.walk(tree):
        # os.getenv("NAME") / environ.get("NAME")
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("getenv", "get") and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            if node.func.attr == "getenv" or _is_environ(node.func.value):
                names.add(node.args[0].value)
        # os.environ["NAME"]
        if (isinstance(node, ast.Subscript) and _is_environ(node.value)
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)):
            names.add(node.slice.value)
    return names


def _is_environ(node) -> bool:
    return ((isinstance(node, ast.Attribute) and node.attr == "environ")
            or (isinstance(node, ast.Name) and node.id == "environ"))


def backend_env_reads() -> dict:
    """Every environment variable the running service reads, to the file that reads it."""
    reads = {}
    for root in BACKEND_SOURCE_ROOTS:
        for directory, subdirectories, files in os.walk(os.path.join(_REPO, root)):
            subdirectories[:] = [d for d in subdirectories if d != "__pycache__"]
            for filename in files:
                # A test may read anything; it is not the deployment's configuration.
                if (not filename.endswith(".py") or filename.startswith("test_")
                        or filename.endswith("_test.py")):
                    continue
                path = os.path.join(directory, filename)
                for name in _env_names_read_by(path):
                    reads.setdefault(name, os.path.relpath(path, _REPO))
    return reads


def delivered_env_names() -> set:
    """
    The names the IaC puts on the Cloud Run container.

    Read from the declaration rather than by matching text, so a name built by any other
    means is absent here too - which is the honest answer, since this test cannot tell
    whether it arrives.
    """
    tree = ast.parse(open(DEPLOY_BACKEND, encoding="utf-8").read())
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if getattr(function, "attr", None) != "ServiceTemplateContainerEnvArgs":
            continue
        for keyword in node.keywords:
            if (keyword.arg == "name" and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)):
                names.add(keyword.value.value)
    return names


def template_variables() -> set:
    """Every variable the operator is asked to supply."""
    names = set()
    for line in open(ENV_TEMPLATE, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        names.add(line.split("=", 1)[0].strip())
    return names


def test_every_variable_the_operator_sets_and_the_backend_reads_is_delivered():
    """
    The invariant that was broken, stated so it cannot break again silently.

    Asking someone to set a value and then not passing it on is worse than not offering
    it: the deployment looks configured and behaves as though it is not.
    """
    reads = backend_env_reads()
    delivered = delivered_env_names()
    undelivered = sorted(name for name in template_variables()
                         if name in reads and name not in delivered)
    assert not undelivered, (
        "env.template asks for these, the backend reads them, and the container never "
        "receives them:\n" + "\n".join(f"    {n}  (read in {reads[n]})" for n in undelivered)
        + "\nAdd each to deploy_backend.py and to BackendServiceConfig.")


def test_every_other_variable_the_backend_reads_is_undelivered_on_purpose():
    """
    The wider half: a setting no deployment can reach is a defect until argued otherwise.

    This is what makes the test about the class. A new `os.getenv` in application code
    fails here until it is either delivered or listed with a reason, so the next instance
    of this bug is caught where it is written rather than in production.
    """
    reads = backend_env_reads()
    delivered = delivered_env_names()
    unexplained = sorted(name for name in reads
                         if name not in delivered and name not in UNDELIVERED_BY_DESIGN
                         and name not in template_variables())
    assert not unexplained, (
        "the backend reads these and no deployment can set them:\n"
        + "\n".join(f"    {n}  (read in {reads[n]})" for n in unexplained)
        + "\nDeliver each through deploy_backend.py, or record why not in "
          "UNDELIVERED_BY_DESIGN.")


def test_the_exception_list_has_no_stale_entries():
    """An exemption that is no longer needed is an exemption nobody will re-examine."""
    reads = backend_env_reads()
    delivered = delivered_env_names()
    stale = sorted(name for name in UNDELIVERED_BY_DESIGN
                   if name not in reads or name in delivered)
    assert not stale, ("UNDELIVERED_BY_DESIGN lists variables that are no longer read, or "
                       "that are now delivered: " + ", ".join(stale))


def test_the_registration_code_flag_reaches_the_container():
    """The instance, kept alongside the class: this is the one that was actually wrong."""
    assert "GLOBAL_DISABLE_REGISTRATION_CODE" in delivered_env_names()


def test_the_declared_configuration_and_the_delivered_environment_agree():
    """
    Every name delivered comes from a field of BackendServiceConfig or from the stack.

    Catches the other direction: a value read from the environment inside deploy_backend
    rather than declared, which would bypass the template and the pre-flight check.
    """
    tree = ast.parse(open(DEPLOY_BACKEND, encoding="utf-8").read())
    direct_reads = {node.args[0].value
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "getenv"
                    and node.args and isinstance(node.args[0], ast.Constant)}
    assert not direct_reads, (
        "deploy_backend.py reads the environment directly: " + ", ".join(sorted(direct_reads))
        + "\nConfiguration arrives through BackendServiceConfig, which __main__.py builds "
          "with getenv so the value is logged, validated and visible.")


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
    print(f"\n{'FAILED' if _failed else 'OK'} - {_failed} failed")
    sys.exit(1 if _failed else 0)
