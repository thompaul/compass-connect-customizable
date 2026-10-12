#!/usr/bin/env python3
"""
One configuration file is the deployment's declared state, so the file has to arrive intact.

The injector used to write only local development files. It now also merges into the
environment file the deployment pipeline uploads, which makes it part of a deployment rather
than part of a developer's workspace, and raises the cost of every way it can be subtly wrong:

- a value the operator set that never reaches anything, because the template does not list it
  and the deployment validates against the template;
- a value that arrives shorter than it left, because an environment file treats whitespace
  followed by `#` as the start of a comment and a partner's attribution line is free text;
- a deployment's own file silently losing to the shipped defaults, or the reverse;
- the infrastructure values in that same file - database URIs, project ids, OAuth credentials -
  being disturbed by a branding change.

Runnable directly: `python3 test_inject_config.py` from the config directory.
"""
import importlib.util
import json
import os
import sys
import tempfile

_CONFIG = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_CONFIG)
ENV_TEMPLATE = os.path.join(_REPO, "iac", "templates", "env.template")

# The script's name is not an identifier, so it cannot be imported by name.
_spec = importlib.util.spec_from_file_location("inject_config", os.path.join(_CONFIG, "inject-config.py"))
inject = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inject)


class Skip(Exception):
    """Raised when a test needs something this interpreter does not have."""


def _write(directory: str, name: str, content: str) -> str:
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    return path


def test_a_deployments_file_is_layered_over_the_shipped_defaults():
    """
    A deployment carries what differs, not a copy of everything.

    The alternative - a partner forking the whole defaults file - is what makes shipped
    improvements unmergeable, and it is how `njira.json` came to exist.
    """
    defaults = {"branding": {"appName": "Compass Connect",
                             "theme": {"brand-primary": "0 255 145", "text-primary": "0 33 71"},
                             "partnerLogos": [{"src": "/a.svg"}, {"src": "/b.svg"}]},
                "cv": {"enabled": True}}
    deployment = {"branding": {"appName": "Horizonte",
                               "theme": {"brand-primary": "27 79 114"},
                               "partnerLogos": [{"src": "/ministry.svg"}]}}
    merged = inject.deep_merge(defaults, deployment)

    assert merged["branding"]["appName"] == "Horizonte", "the deployment's own value wins"
    assert merged["branding"]["theme"]["brand-primary"] == "27 79 114", "its theme key wins"
    assert merged["branding"]["theme"]["text-primary"] == "0 33 71", (
        "a theme key it did not mention still comes from the defaults - otherwise changing one "
        "colour means restating thirty")
    assert merged["branding"]["partnerLogos"] == [{"src": "/ministry.svg"}], (
        "a list replaces rather than merging; half of somebody else's funder list is never "
        "what anybody means")
    assert merged["cv"]["enabled"] is True, "a namespace it did not mention is untouched"


def test_a_deployment_can_remove_something_the_defaults_provide():
    """Without this there is no way to say "not this one" about a default."""
    merged = inject.deep_merge({"faq": {"tutorialVideoUrl": "https://example.org/v"}},
                               {"faq": {"tutorialVideoUrl": None}})
    assert "tutorialVideoUrl" not in merged["faq"]


def test_the_two_tier_maps_do_not_disagree():
    """
    The deployment keeps both tiers' variables in one file, so a name cannot mean two things.

    Checked rather than resolved by precedence: a silent winner here would put one tier's
    value in front of the other's with nothing reporting it.
    """
    inject.deployment_env_map()  # raises if the maps disagree


def test_every_variable_the_injector_writes_is_one_the_deployment_knows():
    """
    The deployment validates against `env.template` and reads what the template lists.

    A mapping the template does not carry is a setting that silently reaches nothing, which is
    how the FAQ video URL came to be documented, shipped, mapped and delivered while the file
    an operator fills in never mentioned it.
    """
    known = inject.template_variables(inject.Path(ENV_TEMPLATE))
    missing = sorted(key for key in inject.deployment_env_map() if key not in known)
    assert not missing, (
        "the injector maps these and env.template does not list them: " + ", ".join(missing))


def test_a_variable_the_template_does_not_know_is_refused():
    """Refused at the point of writing, where it names the variable, rather than at deploy."""
    with tempfile.TemporaryDirectory() as directory:
        # The template knows every mapped variable except the one being injected, so the
        # refusal can only be about that one.
        known = "\n".join(f"{name}=/.*/" for name in inject.deployment_env_map()) + "\n"
        template = _write(directory, "env.template", known)
        env_file = _write(directory, ".env.realm.prod", "")
        config = {"branding": {"appName": "Horizonte"}}

        # It writes cleanly while everything it maps is known.
        inject.update_deployment_env(config, inject.Path(env_file), inject.Path(template))
        assert "GLOBAL_PRODUCT_NAME=Horizonte\n" in open(env_file, encoding="utf-8").read()

        saved = dict(inject.BACKEND_ENV_MAP)
        inject.BACKEND_ENV_MAP["UNKNOWN_TO_THE_DEPLOYMENT"] = "branding.appName"
        try:
            inject.update_deployment_env(config, inject.Path(env_file), inject.Path(template))
        except SystemExit as exit_code:
            assert exit_code.code != 0
        else:
            assert False, "an unknown variable was written instead of being refused"
        finally:
            inject.BACKEND_ENV_MAP.clear()
            inject.BACKEND_ENV_MAP.update(saved)


def test_the_infrastructure_in_the_same_file_is_left_alone():
    """
    Branding and infrastructure share one file, and only one of them is customisation.

    This file holds the database URIs and OAuth credentials for a live environment. A
    branding change that reordered, requoted or dropped any of it would be found at deploy.
    """
    with tempfile.TemporaryDirectory() as directory:
        template = _write(directory, "env.template", "GLOBAL_PRODUCT_NAME=/.*/\nAPPLICATION_MONGODB_URI=<URI>\n")
        original = ("# Databases\n"
                    "APPLICATION_MONGODB_URI=mongodb+srv://user:secret@host/db\n"
                    "\n"
                    "# Branding\n"
                    "GLOBAL_PRODUCT_NAME=Old Name\n")
        env_file = _write(directory, ".env.realm.prod", original)
        inject.update_deployment_env({"branding": {"appName": "Horizonte"}},
                                     inject.Path(env_file), inject.Path(template))
        written = open(env_file, encoding="utf-8").read()

    assert "APPLICATION_MONGODB_URI=mongodb+srv://user:secret@host/db\n" in written, (
        "the database URI was disturbed by a branding change")
    assert "# Databases\n" in written and "# Branding\n" in written, "comments were lost"
    assert "GLOBAL_PRODUCT_NAME=Horizonte\n" in written
    assert "Old Name" not in written, "the old value was left behind rather than replaced"


def test_a_value_carrying_a_hash_survives_the_round_trip():
    """
    The quiet one. `FOOTER=Ranked #1 by the Ministry` reads back as `Ranked`.

    An environment file treats whitespace followed by `#` as the start of a comment, and the
    attribution line is free text a partner writes. Nothing errors; the string is just shorter
    by the time it reaches a browser, three deployment steps later.
    """
    try:
        from dotenv import dotenv_values
    except ImportError:
        raise Skip("python-dotenv is not installed in this interpreter; "
                   "run with the iac venv to cover the parser the pipeline actually uses")

    awkward = "Ranked #1 by the Ministry of Labour"
    with tempfile.TemporaryDirectory() as directory:
        template = _write(directory, "env.template", "FRONTEND_FOOTER_ATTRIBUTION=/.*/\n")
        env_file = _write(directory, ".env.realm.prod", "FRONTEND_FOOTER_ATTRIBUTION=\n")
        inject.update_deployment_env({"branding": {"footerAttribution": awkward}},
                                     inject.Path(env_file), inject.Path(template))
        read_back = dotenv_values(env_file)["FRONTEND_FOOTER_ATTRIBUTION"]

    assert read_back == awkward, f"written {awkward!r}, read back {read_back!r}"


def test_the_json_values_survive_the_round_trip():
    """Theme, locales, funder logos and the sensitive-data schema all travel as JSON."""
    try:
        from dotenv import dotenv_values
    except ImportError:
        raise Skip("python-dotenv is not installed in this interpreter")

    theme = {"brand-primary": "27 79 114", "font-heading": '"Bricolage Grotesque", sans-serif'}
    locales = ["pt-MZ", "en-US"]
    with tempfile.TemporaryDirectory() as directory:
        template = _write(directory, "env.template",
                          "FRONTEND_THEME_CSS_VARIABLES=/.*/\nFRONTEND_SUPPORTED_LOCALES=/.*/\n")
        env_file = _write(directory, ".env.realm.prod", "")
        inject.update_deployment_env(
            {"branding": {"theme": theme}, "i18n": {"ui": {"supportedLocales": locales}}},
            inject.Path(env_file), inject.Path(template))
        values = dotenv_values(env_file)

    assert json.loads(values["FRONTEND_THEME_CSS_VARIABLES"]) == theme
    assert json.loads(values["FRONTEND_SUPPORTED_LOCALES"]) == locales


def test_the_shipped_defaults_are_a_valid_starting_point():
    """Every mapped value in the file we ship coerces to something an env file can carry."""
    config = inject.read_json(inject.Path(os.path.join(_CONFIG, "default.json")))
    updates = inject.build_env_updates(config, inject.deployment_env_map(), None)
    assert updates, "the shipped defaults map to nothing at all"
    for key, raw in updates.items():
        inject.format_deployment_env_value(key, inject.coerce_env_value(raw) or "")


if __name__ == "__main__":
    _failed = _skipped = 0
    for _name, _test in sorted(globals().items()):
        if not _name.startswith("test_") or not callable(_test):
            continue
        try:
            _test()
            print(f"ok   {_name}")
        except Skip as _s:
            _skipped += 1
            print(f"SKIP {_name}: {_s}")
        except AssertionError as _e:
            _failed += 1
            print(f"FAIL {_name}:\n  {_e}")
        except Exception as _e:  # noqa: BLE001 - a test that raises is a test that failed
            _failed += 1
            print(f"FAIL {_name}: raised {type(_e).__name__}: {_e}")
    print(f"\n{'FAILED' if _failed else 'OK'} - {_failed} failed, {_skipped} skipped")
    sys.exit(1 if _failed else 0)
