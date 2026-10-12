#!/usr/bin/env python3
"""
A locale a deployment can select must be one every tier can actually work in.

The frontend offered seven locales and the backend supported six. `ny-ZM` was therefore
selectable in the language menu while the agent could not hold a conversation in it — and
the way that was handled was a line in the partner runbook saying *"do not put `ny-ZM` in
FRONTEND_SUPPORTED_LOCALES; users can select it and the conversation cannot be held in
it."* A documented trap, in a document the operator reads once, about a menu entry their
users see every day.

The lists are three separate declarations in three languages, which is why they drifted:
nothing compared them. These tests are that comparison.

They check the *product's* lists against each other. What a deployment then selects from
them is checked by the injector, which refuses a locale no tier supports at the point the
operator writes it.

Runnable directly: `python3 test_locales.py` from the iac directory.
"""
import ast
import os
import re
import sys

_IAC = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_IAC)

BACKEND_LOCALES = os.path.join(_REPO, "backend", "app", "i18n", "types.py")
FRONTEND_LOCALES = os.path.join(_REPO, "frontend-new", "src", "i18n", "constants.ts")
ADMIN_LOCALES = os.path.join(_REPO, "admin-frontend", "src", "i18n", "constants.ts")

#: Locales a tier knows about but deliberately does not offer, with the reason. A locale
#: whose translations exist but whose conversation does not belongs here rather than in the
#: menu — and it has to be stated, because "not offered" and "forgotten" look identical.
NOT_OFFERED_BY_DESIGN = {
    "ny-ZM": "the interface is translated but the agent has no conversational support for "
             "Chichewa, so offering it would make the conversation fail after the user "
             "had already chosen it",
}


def backend_supported() -> set:
    """`SUPPORTED_LOCALES` in the backend, read as the list of enum members it is."""
    source = open(BACKEND_LOCALES, encoding="utf-8").read()
    tree = ast.parse(source)

    values = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Locale":
            for statement in node.body:
                if (isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Constant)
                        and isinstance(statement.targets[0], ast.Name)):
                    values[statement.targets[0].id] = statement.value.value

    for node in ast.walk(tree):
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
        if target != "SUPPORTED_LOCALES" or not isinstance(node.value, ast.List):
            continue
        return {values[element.attr] for element in node.value.elts
                if isinstance(element, ast.Attribute) and element.attr in values}

    raise AssertionError(f"no SUPPORTED_LOCALES list found in {BACKEND_LOCALES}")


def _typescript_locales(path: str, name: str) -> set:
    """A `Locale[]` array in a TypeScript constants file, resolved through the enum."""
    source = open(path, encoding="utf-8").read()
    members = dict(re.findall(r'^\s*([A-Z_0-9]+)\s*=\s*"([^"]+)",', source, re.M))

    body = re.search(rf"export const {name}: Locale\[\] = \[(.*?)\];", source, re.S)
    assert body, f"no {name} array found in {path}"
    return {members[member] for member in re.findall(r"Locale\.([A-Z_0-9]+)", body.group(1))
            if member in members}


def _typescript_known(path: str) -> set:
    """Every member of the `Locale` enum, offered or not."""
    source = open(path, encoding="utf-8").read()
    body = re.search(r"export enum Locale \{(.*?)\n\}", source, re.S)
    assert body, f"no Locale enum found in {path}"
    return set(re.findall(r'=\s*"([^"]+)"', body.group(1)))


def frontend_offered() -> set:
    return _typescript_locales(FRONTEND_LOCALES, "SupportedLocales")


def admin_offered() -> set:
    return _typescript_locales(ADMIN_LOCALES, "SupportedLocales")


def test_every_locale_a_user_can_select_is_one_the_agent_can_converse_in():
    """
    The defect this stage exists to close, stated as the invariant it violated.

    A user picks a language from a menu. If the backend cannot work in it, they find out
    after choosing, in the middle of a conversation, in a language they cannot read the
    error in.
    """
    offered = frontend_offered()
    supported = backend_supported()
    unsupported = sorted(offered - supported)
    assert not unsupported, (
        "the interface offers locales the backend cannot converse in: "
        + ", ".join(unsupported)
        + f"\nBackend supports: {', '.join(sorted(supported))}"
        + "\nEither add them to backend/app/i18n/types.py, or stop offering them in "
          "frontend-new/src/i18n/constants.ts and say why in NOT_OFFERED_BY_DESIGN.")


def test_no_locale_the_backend_supports_is_unreachable():
    """
    The other direction, which is a smaller fault but still a fault.

    A locale the agent can work in and no interface offers is work nobody can use, and the
    reason is always that somebody updated one list of three.
    """
    unreachable = sorted(backend_supported() - frontend_offered())
    assert not unreachable, (
        "the backend supports locales no interface offers: " + ", ".join(unreachable)
        + "\nAdd them to frontend-new/src/i18n/constants.ts, or remove them from the backend.")


def test_the_admin_panel_offers_the_same_locales_as_the_frontend():
    """Both read one `FRONTEND_SUPPORTED_LOCALES`, so a divergence is a silent fallback."""
    difference = sorted(frontend_offered() ^ admin_offered())
    assert not difference, (
        "the frontend and the admin panel offer different locales: " + ", ".join(difference)
        + "\nThey are configured from the same variable, so one of them silently falls back.")


def test_a_locale_that_is_known_but_not_offered_says_why():
    """
    An entry left in the enum and out of the menu is either deliberate or an oversight, and
    nothing in the code distinguishes them. This makes the deliberate ones say so.
    """
    unexplained = sorted(_typescript_known(FRONTEND_LOCALES) - frontend_offered()
                         - set(NOT_OFFERED_BY_DESIGN))
    assert not unexplained, (
        "these are in the Locale enum and not offered, with no reason recorded: "
        + ", ".join(unexplained)
        + "\nOffer them, remove them, or record why not in NOT_OFFERED_BY_DESIGN.")


def test_the_not_offered_list_has_no_stale_entries():
    """An exemption that no longer applies is an exemption nobody will re-examine."""
    offered = frontend_offered()
    known = _typescript_known(FRONTEND_LOCALES)
    stale = sorted(name for name in NOT_OFFERED_BY_DESIGN
                   if name in offered or name not in known)
    assert not stale, (
        "NOT_OFFERED_BY_DESIGN lists locales that are now offered, or that no longer exist: "
        + ", ".join(stale))


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
