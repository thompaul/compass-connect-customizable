#!/usr/bin/env python3
"""
Nothing a deployment falls back to belongs to another organisation.

An unconfigured deployment used to present itself as Njila: Njila's wordmark at seven
places in the interface and five more in the admin panel, Njila's name as the product
name, Njila's privacy policy and terms of use, a contact address at njila.ai, the World
Bank and a ministry credited in the footer, and a shipped configuration file that was
Njila's deployment - down to the Google Analytics property its users' behaviour would
have been sent to. None of it was a decision; it was the first deployment's values left
where the defaults go.

These tests state the rule that replaced it: what a deployment has not configured, it
does not claim. They check the three places a borrowed identity can hide - the files
shipped in the browser bundles, the values shipped as defaults, and the fallbacks written
into the source.

Runnable directly: `python3 test_no_partner_defaults.py` from the iac directory.
"""
import json
import os
import re
import sys

_IAC = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_IAC)

BUNDLE_ROOTS = ("frontend-new/public", "admin-frontend/public")
SOURCE_ROOTS = ("frontend-new/src", "admin-frontend/src")
SHIPPED_CONFIG = os.path.join(_REPO, "config", "default.json")

#: Organisations that are somebody else's: partner deployments, their funders, and the
#: institutions they credit. Tabiya is deliberately absent - the product may name its own
#: author in an attribution line - but Tabiya's *logo* is a funder mark like any other and
#: is covered by the bundle check below.
PARTNER_TERMS = ("njila", "njira", "njiramoz", "world bank", "world-bank",
                 "ministry of technology", "ministry-tech", "oxford")

#: Marks that must not ship in a browser bundle, by the names they were committed under.
FUNDER_ASSET_TERMS = PARTNER_TERMS + ("tabiya-logo", "tabiya_logo", "google.org")

#: Source files that may name a partner, each because it carries that partner's own
#: content rather than a default anybody inherits. The reason is the point: without one,
#: this list is just a way of not fixing things.
SOURCE_EXEMPTIONS = {
    "frontend-new/src/legal/legalDocumentLoader.ts":
        "a compatibility shim keyed by product name, so the two deployments that predate "
        "configurable legal content keep theirs; the default resolves to a placeholder",
    "frontend-new/src/knowledgeHub/components/SectorProfile/sectorStaticData.ts":
        "the country-specific sector catalogue, which becomes optional and configured "
        "rather than looked up by product name in its own stage",
}

#: Directories of partner-authored prose. Making these supplied per deployment rather than
#: compiled into the bundle is the content-bundle work of the next phase.
CONTENT_DIRECTORIES = ("frontend-new/src/legal/documents",
                       "frontend-new/src/faq/documents")

#: Locale files carry translations, and in Chichewa "njila"/"njira" is the ordinary word
#: for a path or a way. A brand check cannot tell the two apart, so it does not try.
LOCALE_DIRECTORY = os.sep + "i18n" + os.sep + "locales" + os.sep


def _relative(path: str) -> str:
    return os.path.relpath(path, _REPO).replace(os.sep, "/")


def _walk(root: str):
    for directory, subdirectories, files in os.walk(os.path.join(_REPO, root)):
        subdirectories[:] = [d for d in subdirectories
                             if d not in ("node_modules", "build", "__pycache__")]
        for filename in files:
            yield os.path.join(directory, filename)


def test_no_browser_bundle_ships_a_partner_or_funder_mark():
    """
    The plainest form of the rule: the files are not there to be served by accident.

    A logo left in `public/` reaches every deployment's bucket whether or not anything
    references it, so removing the references is not enough.
    """
    offenders = []
    for root in BUNDLE_ROOTS:
        for path in _walk(root):
            name = os.path.basename(path).lower()
            if any(term in name for term in FUNDER_ASSET_TERMS):
                offenders.append(_relative(path))
    assert not offenders, (
        "these partner or funder marks ship in a browser bundle:\n"
        + "\n".join(f"    {p}" for p in sorted(offenders))
        + "\nA deployment supplies its own through the branding configuration.")


def test_the_shipped_configuration_names_no_partner():
    """
    The defaults a partner starts from must be the product's, not the first partner's.

    This file was one deployment's own, which meant a partner who changed only the name
    kept that deployment's colours, its funders' logos and - least visibly and most
    seriously - its Google Analytics and Tag Manager properties.
    """
    config = json.loads(open(SHIPPED_CONFIG, encoding="utf-8").read())
    offenders = []

    def visit(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                visit(value, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                visit(value, f"{path}[{index}]")
        elif isinstance(node, str):
            lowered = node.lower()
            for term in FUNDER_ASSET_TERMS:
                if term in lowered:
                    offenders.append(f"{path} = {node!r}")

    visit(config, "")
    assert not offenders, (
        "config/default.json carries another organisation's values:\n"
        + "\n".join(f"    {o}" for o in sorted(offenders))
        + "\nThe shipped defaults are Compass Connect's; a deployment's own go in its own file.")


def test_the_shipped_configuration_claims_no_analytics_property():
    """
    Separate from the name check because an account id names nobody.

    An analytics id left in the defaults sends a partner's users' behaviour to whoever owns
    that property, and nothing in the interface would show it.
    """
    config = json.loads(open(SHIPPED_CONFIG, encoding="utf-8").read())
    analytics = config.get("analytics", {})
    claimed = sorted(key for key, value in analytics.items()
                     if isinstance(value, str) and value.strip())
    assert not claimed, (
        "config/default.json ships analytics identifiers: " + ", ".join(claimed)
        + "\nA deployment measures itself, or measures nothing.")
    assert analytics.get("enabled") is False, (
        "analytics is enabled by default, so a deployment that has supplied no identifiers "
        "still tries to report.")


def test_no_source_fallback_resolves_to_a_partner():
    """
    The form the fault actually took: `getDarkLogoUrl() || "/njila-logo-dark.svg"`.

    Written once it looks like a sensible default. Written at twelve call sites it is the
    product's identity, and every one of them had to be found by hand to change it.
    """
    offenders = {}
    for root in SOURCE_ROOTS:
        for path in _walk(root):
            if not path.endswith((".ts", ".tsx")):
                continue
            relative = _relative(path)
            if relative in SOURCE_EXEMPTIONS:
                continue
            if LOCALE_DIRECTORY in path or any(relative.startswith(d) for d in CONTENT_DIRECTORIES):
                continue
            try:
                source = open(path, encoding="utf-8").read().lower()
            except UnicodeDecodeError:
                continue
            hits = sorted({term for term in PARTNER_TERMS if term in source})
            if hits:
                offenders[relative] = hits
    assert not offenders, (
        "these name a partner outside the places allowed to:\n"
        + "\n".join(f"    {p}  ({', '.join(h)})" for p, h in sorted(offenders.items()))
        + "\nResolve branding through the brand asset helpers, which fall back to the "
          "product's own marks.")


def test_the_source_exemptions_are_still_needed():
    """An exemption that no longer applies is an exemption nobody will re-examine."""
    stale = []
    for relative in SOURCE_EXEMPTIONS:
        path = os.path.join(_REPO, relative)
        if not os.path.exists(path):
            stale.append(f"{relative} (no longer exists)")
            continue
        source = open(path, encoding="utf-8").read().lower()
        if not any(term in source for term in PARTNER_TERMS):
            stale.append(f"{relative} (no longer names a partner)")
    assert not stale, ("SOURCE_EXEMPTIONS is out of date:\n"
                       + "\n".join(f"    {s}" for s in stale))


def test_an_unconfigured_deployment_shows_no_partner_legal_documents():
    """
    The exposure that mattered most, named on its own so it cannot regress quietly.

    A privacy policy identifies the organisation accountable for a user's data. Showing
    one belonging to a party that never receives that data is not a cosmetic default.
    """
    loader = os.path.join(_REPO, "frontend-new/src/legal/legalDocumentLoader.ts")
    source = open(loader, encoding="utf-8").read()
    fallback = re.search(r"\?\?\s*([A-Za-z_][A-Za-z0-9_]*)", source)
    assert fallback, "the legal document loader no longer has a single fallback to check"
    assert fallback.group(1) == "NOT_CONFIGURED", (
        f"the legal documents fall back to {fallback.group(1)}; an unconfigured deployment "
        "must be told it has published none, not handed another organisation's.")


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
