#!/usr/bin/env python3
"""
A deployment's settings can be committed. Its credentials cannot. They were in one file.

Because they shared a file, the file inherited the stricter rule, and none of it could go in a
repository — which is why a partner cannot own their own configuration: there is nothing
committable to own. Separating them is the precondition for the partner repository, for the
template a partner copies, and for a deploy pipeline.

The separation rots quietly. Nobody adds a password to a file marked "do not put passwords
here"; they add a variable that happens to be one, to the file that already holds the rest.
That is how the file got this way. So these tests check the rule rather than trusting it.

Runnable directly: `python3 test_config_secrets_split.py` from the iac directory.
"""
import importlib.util
import os
import re
import sys

_IAC = os.path.dirname(os.path.abspath(__file__))
_TEMPLATES = os.path.join(_IAC, "templates")

_spec = importlib.util.spec_from_file_location(
    "deployment_env", os.path.join(_IAC, "lib", "deployment_env.py"))
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

declared_secret_names = _module.declared_secret_names
parse_env = _module.parse_env
assemble = _module.assemble
secrets_in = _module.secrets_in
required_secret_names = _module.required_secret_names

# Names that are credentials whatever they are called. Not the declaration — a second opinion,
# so that a credential added under a new name is noticed rather than waved through.
LOOKS_LIKE_A_SECRET = ("SECRET", "PASSWORD", "_KEY", "TOKEN", "_URI", "CREDENTIAL", "PRIVATE", "DSN")


def test_the_product_declares_which_variables_are_credentials():
    names = declared_secret_names(_TEMPLATES)
    assert names, "no credentials are declared, so nothing can be kept out of a repository"
    assert len(names) == len(set(names)), "a credential is declared twice"


def test_every_declared_credential_exists_in_the_template():
    """
    A declaration naming a variable the product does not have is a rule nobody can break and
    nobody can satisfy. It also hides the opposite mistake: a credential that was renamed and
    is now unprotected under its new name.
    """
    template = open(os.path.join(_TEMPLATES, "env.template"), encoding="utf-8").read()
    present = {m.group(1) for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=", template, re.M)}
    missing = [n for n in declared_secret_names(_TEMPLATES) if n not in present]
    assert not missing, (
        "these are declared as credentials but the product has no such variable:\n    "
        + "\n    ".join(missing))


def test_nothing_credential_shaped_escapes_the_declaration():
    """
    The second opinion. A variable whose name says credential, that the declaration does not
    name, is either a credential nobody protected or a name that misleads every reader.
    """
    template = open(os.path.join(_TEMPLATES, "env.template"), encoding="utf-8").read()
    declared = set(declared_secret_names(_TEMPLATES))
    suspicious = sorted(
        name for name in {m.group(1) for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=", template, re.M)}
        if any(fragment in name for fragment in LOOKS_LIKE_A_SECRET) and name not in declared)
    # Known exceptions: names that contain a credential word and are not credentials.
    allowed = {"SENSITIVE_PERSONAL_DATA_FIELDS", "FRONTEND_SENSITIVE_DATA_FIELDS",
               "PLAIN_PERSONAL_DATA_FIELDS", "ADMIN_FIREBASE_TENANT_ID"}
    suspicious = [n for n in suspicious if n not in allowed]
    assert not suspicious, (
        "these are named like credentials and are not declared as any:\n    "
        + "\n    ".join(suspicious)
        + "\nDeclare them in templates/secret-variables.txt, or rename them so a reader is not "
          "misled.")


def test_a_credential_can_arrive_from_a_pipeline_without_touching_disk():
    """
    Continuous integration holds these in its own secret store and passes them as environment
    variables. Requiring a file would mean writing every credential to disk beside the
    configuration, which is the arrangement being dismantled.
    """
    assembled, missing = assemble(
        config_values={"GLOBAL_PRODUCT_NAME": "Acme"},
        secret_values={},
        environment={"APPLICATION_MONGODB_URI": "mongodb://from-the-pipeline"},
        secret_names=["APPLICATION_MONGODB_URI"],
        required_names=["APPLICATION_MONGODB_URI"],
    )
    assert not missing, "a credential supplied by the environment was reported as missing"
    assert assembled["APPLICATION_MONGODB_URI"] == "mongodb://from-the-pipeline"
    assert assembled["GLOBAL_PRODUCT_NAME"] == "Acme", "the configuration half was lost"


def test_a_secrets_file_wins_over_the_environment():
    """An operator deploying by hand has a file; it is the more specific statement of intent."""
    assembled, _ = assemble(
        config_values={},
        secret_values={"BACKEND_SENTRY_DSN": "from-the-file"},
        environment={"BACKEND_SENTRY_DSN": "from-the-environment"},
        secret_names=["BACKEND_SENTRY_DSN"],
        required_names=["BACKEND_SENTRY_DSN"],
    )
    assert assembled["BACKEND_SENTRY_DSN"] == "from-the-file"


def test_every_missing_credential_is_reported_at_once():
    """
    One per attempt means one deploy per credential. An operator setting a deployment up for
    the first time is missing several, and should be told all of them.
    """
    _, missing = assemble(
        config_values={}, secret_values={}, environment={},
        secret_names=["A_URI", "B_TOKEN", "C_SECRET"],
        required_names=["A_URI", "B_TOKEN", "C_SECRET"],
    )
    assert missing == ["A_URI", "B_TOKEN", "C_SECRET"], (
        f"expected all three reported together, got {missing}")


def test_a_credential_left_in_the_committable_half_is_noticed():
    """
    It still works — a deployment mid-migration must not break — but it is reported, because
    the file it is in is the one about to be committed.
    """
    config = {"APPLICATION_MONGODB_URI": "mongodb://still-here", "GLOBAL_PRODUCT_NAME": "Acme"}
    names = ["APPLICATION_MONGODB_URI"]
    assembled, missing = assemble(
        config_values=config, secret_values={}, environment={}, secret_names=names,
        required_names=names)
    assert not missing, "a credential present in the configuration half was called missing"
    assert assembled["APPLICATION_MONGODB_URI"] == "mongodb://still-here"
    assert secrets_in(config, names) == ["APPLICATION_MONGODB_URI"], (
        "a credential in the committable file is not reported, so nobody learns to move it")


def test_setup_env_refuses_rather_than_deploying_without_a_credential():
    source = open(os.path.join(_IAC, "scripts", "setup_env.py"), encoding="utf-8").read()
    assert "if missing:" in source and "exit(1)" in source, (
        "setup_env.py deploys when a credential has no value, so the deployment starts and "
        "fails later against a service it cannot reach")
    assert "tempfile.mkstemp" in source, (
        "the assembled environment is written to a predictable path rather than a private "
        "temporary file")
    assert "os.remove(assembled_path)" in source, (
        "the assembled environment, which holds every credential, is left on disk")



def test_a_credential_the_deployment_does_not_use_is_not_demanded():
    """
    Declared-secret and required are different things, and conflating them refused to deploy a
    configuration that was correct.

    This product supports more than one LLM provider and several optional services. A
    deployment using Gemini sets `ANTHROPIC_API_KEY` to nothing deliberately, and one with no
    matching service does the same with `MATCHING_SERVICE_API_KEY`. Both are credentials; both
    are optional; demanding them turns a working deployment into a failed one.

    The template already says which is which, so requiredness is read rather than declared
    twice.
    """
    required = set(required_secret_names(_TEMPLATES))
    declared = set(declared_secret_names(_TEMPLATES))

    assert required <= declared, "something is required that is not declared a credential"
    assert required != declared, (
        "every declared credential is treated as required, so a deployment that does not use "
        "an optional service cannot deploy")

    for optional in ("ANTHROPIC_API_KEY", "MATCHING_SERVICE_API_KEY"):
        assert optional in declared, f"{optional} is no longer protected as a credential"
        assert optional not in required, (
            f"{optional} is demanded of every deployment, including those that do not use it")

    for always in ("APPLICATION_MONGODB_URI", "GCP_OAUTH_CLIENT_SECRET"):
        assert always in required, f"{always} is optional, so a deployment can start without it"


def test_an_empty_value_is_carried_through_rather_than_treated_as_absent():
    """
    `MATCHING_SERVICE_API_KEY=` is a statement: this deployment has no matching service.
    Dropping it changes the environment the backend sees, and the assembled result has to be
    identical to the file it replaces or the migration is not safe to perform.
    """
    assembled, missing = assemble(
        config_values={}, secret_values={"MATCHING_SERVICE_API_KEY": ""},
        environment={}, secret_names=["MATCHING_SERVICE_API_KEY"], required_names=[])
    assert not missing
    assert "MATCHING_SERVICE_API_KEY" in assembled, "the deliberate empty value was dropped"
    assert assembled["MATCHING_SERVICE_API_KEY"] == ""


def test_a_required_credential_that_is_present_and_empty_is_missing():
    """Set to nothing is not supplied, when the deployment cannot work without it."""
    _, missing = assemble(
        config_values={}, secret_values={"APPLICATION_MONGODB_URI": ""},
        environment={}, secret_names=["APPLICATION_MONGODB_URI"],
        required_names=["APPLICATION_MONGODB_URI"])
    assert missing == ["APPLICATION_MONGODB_URI"], (
        "an empty required credential was accepted, so the deployment starts and fails against "
        "a database it cannot reach")

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
