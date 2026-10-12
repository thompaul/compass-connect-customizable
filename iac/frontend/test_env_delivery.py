#!/usr/bin/env python3
"""
Everything the browser is asked to read must actually reach `env.js`.

The backend had this fault and it cost a working registration form: a variable in
`env.template`, read by the application, and absent from the hand-written list that puts
it on the container. The two browser tiers are built the same way — a dict literal in a
preparation script, derived from nothing and compared with nothing — so they have the
same fault, and the admin panel had it: it has read a dark logo at five call sites since
it was written, and `prepare_admin_frontend.py` never put that name in its `env.js`.

These tests compare the three declarations that have to agree: the variables the
interface reads (`EnvVariables`), the variables the operator is asked to set
(`env.template`), and the variables the deployment actually writes into `env.js`.

Runnable directly: `python3 frontend/test_env_delivery.py` from the iac directory.
"""
import ast
import os
import re
import sys

_IAC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.dirname(_IAC)

ENV_TEMPLATE = os.path.join(_IAC, "templates", "env.template")

#: Each browser tier: the module declaring what it reads, and the script that delivers it.
TIERS = {
    "frontend": (
        os.path.join(_REPO, "frontend-new", "src", "envService.ts"),
        os.path.join(_IAC, "frontend", "prepare_frontend.py"),
    ),
    "admin frontend": (
        os.path.join(_REPO, "admin-frontend", "src", "envService.ts"),
        os.path.join(_IAC, "admin_frontend", "prepare_admin_frontend.py"),
    ),
}

#: Variables an interface declares that its deployment deliberately does not deliver.
#: Each needs a reason, because the default has to be that an unreachable setting is a
#: defect: the interface offers a knob that no deployment can turn.
UNDELIVERED_BY_DESIGN = {
    "frontend": {},
    "admin frontend": {},
}


#: Names the deployment works out for itself and an operator never supplies: stack outputs,
#: the environment's own name, the credentials the auth stack produces. These are delivered
#: and read, and their absence from the template is correct rather than an oversight.
DERIVED_AT_DEPLOY_TIME = {
    "BACKEND_URL": "an output of the backend stack",
    "TARGET_ENVIRONMENT_NAME": "derived from the stack name",
    "FIREBASE_API_KEY": "an output of the auth stack",
    "FIREBASE_AUTH_DOMAIN": "an output of the auth stack",
    "ADMIN_FRONTEND_FIREBASE_PROJECT_ID": "the environment's own project id",
    "FRONTEND_CONTENT_DOCUMENTS": "read from the documents the operator put in assets/content, "
                                  "so there is nothing for them to also write down",
}


def declared_variables(env_service_path: str) -> set:
    """
    The names the interface reads, from its `EnvVariables` enum.

    Read from the enum rather than from call sites, because every read goes through it:
    `getEnv` takes an `EnvVariables`, so a name that is not a member cannot be read.
    """
    source = open(env_service_path, encoding="utf-8").read()
    body = re.search(r"enum EnvVariables\s*\{(.*?)\n\}", source, re.S)
    assert body, f"no EnvVariables enum in {env_service_path}"
    return set(re.findall(r'^\s*([A-Z][A-Z0-9_]*)\s*=', body.group(1), re.M))


def delivered_variables(prepare_script_path: str) -> set:
    """
    The names the deployment writes into `env.js`.

    Read from the dict literal rather than by matching text, so a name assembled by any
    other means is absent here too - which is the honest answer, since this test cannot
    tell whether it arrives.
    """
    tree = ast.parse(open(prepare_script_path, encoding="utf-8").read())
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        # The env.js map is the one that carries the backend URL; no other dict here does.
        if "BACKEND_URL" in keys:
            names |= keys
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


def test_every_variable_the_operator_sets_and_an_interface_reads_is_delivered():
    """
    Asking someone to set a value and then not passing it on is worse than not offering
    it: the deployment looks configured and behaves as though it is not.
    """
    failures = []
    for tier, (env_service, prepare_script) in TIERS.items():
        declared = declared_variables(env_service)
        delivered = delivered_variables(prepare_script)
        missing = sorted(name for name in template_variables()
                         if name in declared and name not in delivered)
        if missing:
            failures.append(f"  {tier}: {', '.join(missing)}")
    assert not failures, (
        "env.template asks for these, the interface reads them, and env.js never carries "
        "them:\n" + "\n".join(failures)
        + "\nAdd each to the tier's prepare script, in both the reads and the env.js map.")


def test_every_other_variable_an_interface_reads_is_undelivered_on_purpose():
    """
    The wider half: a setting no deployment can reach is a defect until argued otherwise.

    A new member of `EnvVariables` fails here until it is either delivered or listed with
    a reason, so the next instance of this bug is caught where it is written.
    """
    failures = []
    for tier, (env_service, prepare_script) in TIERS.items():
        declared = declared_variables(env_service)
        delivered = delivered_variables(prepare_script)
        unexplained = sorted(name for name in declared
                             if name not in delivered
                             and name not in UNDELIVERED_BY_DESIGN[tier]
                             and name not in template_variables())
        if unexplained:
            failures.append(f"  {tier}: {', '.join(unexplained)}")
    assert not failures, (
        "these are read by an interface and no deployment can set them:\n"
        + "\n".join(failures)
        + "\nDeliver each through the tier's prepare script, or record why not in "
          "UNDELIVERED_BY_DESIGN.")


def test_the_exception_lists_have_no_stale_entries():
    """An exemption that is no longer needed is an exemption nobody will re-examine."""
    stale = []
    for tier, (env_service, prepare_script) in TIERS.items():
        declared = declared_variables(env_service)
        delivered = delivered_variables(prepare_script)
        for name in UNDELIVERED_BY_DESIGN[tier]:
            if name not in declared or name in delivered:
                stale.append(f"  {tier}: {name}")
    assert not stale, ("UNDELIVERED_BY_DESIGN lists variables that are no longer read, or "
                       "that are now delivered:\n" + "\n".join(stale))


def test_every_setting_that_works_is_one_the_operator_can_discover():
    """
    The third direction, and the quietest: delivered, read, and in no template.

    `env.template` is both the validator and the only list of what a deployment can be told.
    A variable that works perfectly but appears in no template is a setting nobody will find
    - `FRONTEND_FAQ_TUTORIAL_VIDEO_URL` was documented in the customisation guide, shipped in
    the default configuration, mapped by the injector and delivered to the browser, while the
    file an operator actually fills in never mentioned it.
    """
    template = template_variables()
    failures = []
    for tier, (env_service, prepare_script) in TIERS.items():
        working = declared_variables(env_service) & delivered_variables(prepare_script)
        undiscoverable = sorted(working - template - set(DERIVED_AT_DEPLOY_TIME))
        if undiscoverable:
            failures.append(f"  {tier}: {', '.join(undiscoverable)}")
    assert not failures, (
        "these reach the browser and no template tells an operator they exist:\n"
        + "\n".join(failures)
        + "\nAdd each to env.template, or record it in DERIVED_AT_DEPLOY_TIME if the "
          "deployment works it out rather than being told it.")


def test_nothing_derived_at_deploy_time_is_also_asked_of_the_operator():
    """Asking for a value the deployment overwrites wastes the operator's time and confuses."""
    template = template_variables()
    asked = sorted(name for name in DERIVED_AT_DEPLOY_TIME if name in template)
    assert not asked, (
        "env.template asks for these and the deployment derives them anyway: "
        + ", ".join(asked))


def test_the_admin_panel_receives_the_logo_it_reads():
    """The instance, kept alongside the class: this is the one that was actually wrong."""
    _, prepare_script = TIERS["admin frontend"]
    assert "FRONTEND_DARK_LOGO_URL" in delivered_variables(prepare_script)


def test_the_branding_an_operator_can_set_reaches_both_tiers_that_show_it():
    """
    Branding is the configuration a partner is most likely to set and least likely to
    check twice, because a wrong logo looks like a wrong logo rather than like a bug.
    """
    shared = {"GLOBAL_PRODUCT_NAME", "FRONTEND_LOGO_URL", "FRONTEND_DARK_LOGO_URL",
              "FRONTEND_FAVICON_URL", "FRONTEND_APP_ICON_URL", "FRONTEND_PARTNER_LOGOS",
              "FRONTEND_THEME_CSS_VARIABLES", "FRONTEND_CONTACT_EMAIL",
              "FRONTEND_FOOTER_ATTRIBUTION"}
    for tier, (env_service, prepare_script) in TIERS.items():
        delivered = delivered_variables(prepare_script)
        declared = declared_variables(env_service)
        missing = sorted((shared & declared) - delivered)
        assert not missing, f"{tier} reads but never receives: {', '.join(missing)}"


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
