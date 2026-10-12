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
        # Every mapped variable, because setting one namespace can derive several.
        template = _write(directory, "env.template",
                          "\n".join(f"{name}=/.*/" for name in inject.deployment_env_map()) + "\n")
        env_file = _write(directory, ".env.realm.prod", "")
        inject.update_deployment_env(
            {"branding": {"theme": theme},
             "i18n": {"defaultLocale": "pt-MZ", "locales": [{"locale": name} for name in locales]}},
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


def _derive(config):
    """Build the deployment's env updates for one configuration, as the injector would."""
    return inject.build_env_updates(config, inject.deployment_env_map(), None)


def test_language_is_declared_once_and_arrives_in_both_shapes():
    """
    The menu and the agent are built from the same sentence.

    They used to be two settings in two shapes - a list of locales for the browser, a
    structured value with per-locale date formats for the backend - and nothing compared
    them, so a locale could be in the menu and missing from the agent.
    """
    updates = _derive({"i18n": {
        "defaultLocale": "pt-MZ",
        "locales": [{"locale": "pt-MZ", "dateFormat": "DD/MM/YYYY"},
                    {"locale": "en-US", "dateFormat": "YYYY/MM/DD"}],
    }})

    assert updates["FRONTEND_DEFAULT_LOCALE"] == "pt-MZ"
    assert updates["FRONTEND_SUPPORTED_LOCALES"] == ["pt-MZ", "en-US"]
    assert updates["BACKEND_LANGUAGE_CONFIG"] == {
        "default_locale": "pt-MZ",
        "available_locales": [{"locale": "pt-MZ", "date_format": "DD/MM/YYYY"},
                              {"locale": "en-US", "date_format": "YYYY/MM/DD"}],
    }, "the backend's shape disagrees with the menu built from the same declaration"


def test_the_menu_and_the_agent_cannot_be_given_different_locales():
    """The property that matters, asserted rather than assumed from the shapes above."""
    updates = _derive({"i18n": {
        "defaultLocale": "en-US",
        "locales": [{"locale": "en-US"}, {"locale": "sw-KE"}, {"locale": "es-AR"}],
    }})
    menu = set(updates["FRONTEND_SUPPORTED_LOCALES"])
    agent = {entry["locale"] for entry in updates["BACKEND_LANGUAGE_CONFIG"]["available_locales"]}
    assert menu == agent, f"menu offers {sorted(menu)}, agent supports {sorted(agent)}"
    assert updates["FRONTEND_DEFAULT_LOCALE"] == updates["BACKEND_LANGUAGE_CONFIG"]["default_locale"]


def test_a_default_locale_nobody_can_select_is_refused():
    """A default outside the list is the backend refusing to start, found at deploy."""
    try:
        _derive({"i18n": {"defaultLocale": "fr-FR", "locales": [{"locale": "en-US"}]}})
    except SystemExit as exit_code:
        assert exit_code.code != 0
    else:
        assert False, "a default locale outside the declared list was accepted"


def test_the_superseded_two_part_shape_is_refused_rather_than_ignored():
    """
    The old shape would otherwise map to nothing, and a deployment whose language silently
    stopped being configured reads as a deployment that was never configured.
    """
    try:
        _derive({"i18n": {"ui": {"defaultLocale": "en-US", "supportedLocales": ["en-US"]},
                          "conversation": {"default_locale": "en-US", "available_locales": []}}})
    except SystemExit as exit_code:
        assert exit_code.code != 0
    else:
        assert False, "the superseded i18n shape was accepted and quietly produced nothing"


def test_a_locale_listed_twice_is_refused():
    """Duplicates reach the menu as duplicates, which looks like a rendering bug."""
    try:
        _derive({"i18n": {"defaultLocale": "en-US",
                          "locales": [{"locale": "en-US"}, {"locale": "en-US"}]}})
    except SystemExit as exit_code:
        assert exit_code.code != 0
    else:
        assert False, "a duplicate locale was accepted"


def test_a_deployment_that_says_nothing_about_language_gets_nothing_derived():
    """Deriving an empty language config would be worse than deriving none."""
    updates = _derive({"branding": {"appName": "Horizonte"}})
    for key in ("FRONTEND_DEFAULT_LOCALE", "FRONTEND_SUPPORTED_LOCALES", "BACKEND_LANGUAGE_CONFIG"):
        assert key not in updates, f"{key} was derived from a configuration that set no locales"


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
        except SystemExit as _e:
            # The injector exits on bad configuration. A test that did not expect that must
            # be reported, not allowed to end the run before the summary is printed.
            _failed += 1
            print(f"FAIL {_name}: exited with code {_e.code}")
        except Exception as _e:  # noqa: BLE001 - a test that raises is a test that failed
            _failed += 1
            print(f"FAIL {_name}: raised {type(_e).__name__}: {_e}")
    print(f"\n{'FAILED' if _failed else 'OK'} - {_failed} failed, {_skipped} skipped")
    sys.exit(1 if _failed else 0)
