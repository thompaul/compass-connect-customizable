#!/usr/bin/env python3
"""
The example deployments have to be deployable, or they teach the wrong thing.

`config/examples/` holds two invented deployments, and their job is to be switched between:
apply one, apply the other, and see what deployment-time configuration reaches. That only
works if they are correct, and nothing about a JSON file and a directory of SVGs announces
when it stops being correct. A logo path that matches no file, a document in a language the
deployment does not offer, a setting the deployment pipeline does not know - all three are
silent, and all three would be discovered by a person following the instructions.

So they are checked the way a deployment checks them: by the code that would refuse them.

Runnable directly: `python3 test_examples.py` from the config directory.
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile

_CONFIG = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_CONFIG)
EXAMPLES = os.path.join(_CONFIG, "examples")
ENV_TEMPLATE = os.path.join(_REPO, "iac", "templates", "env.template")

_spec = importlib.util.spec_from_file_location("inject_config", os.path.join(_CONFIG, "inject-config.py"))
inject = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inject)

branding_assets = inject._load_branding_assets()


def example_names() -> list:
    return sorted(name for name in os.listdir(EXAMPLES)
                  if os.path.isdir(os.path.join(EXAMPLES, name)))


def example_config(name: str) -> dict:
    with open(os.path.join(EXAMPLES, name, f"{name}.json"), encoding="utf-8") as handle:
        return json.load(handle)


def merged_config(name: str) -> dict:
    """What the deployment would actually run with: the shipped defaults under the example."""
    from pathlib import Path
    return inject.load_layered_config(Path(inject.DEFAULT_DEFAULTS_PATH),
                                      [Path(os.path.join(EXAMPLES, name, f"{name}.json"))])


def test_there_are_at_least_two_examples_and_they_differ():
    """
    One example is a template. Two are a test.

    The question these answer is not "can a deployment be configured" but "can a configured
    deployment be changed into a different one", which is the thing a partner will actually
    do and the thing nothing had ever demonstrated.
    """
    names = example_names()
    assert len(names) >= 2, f"only {names} - switching between deployments cannot be shown"

    configs = {name: merged_config(name) for name in names}
    for field, path in (("product name", ("branding", "appName")),
                        ("theme", ("branding", "theme")),
                        ("default locale", ("i18n", "defaultLocale"))):
        values = []
        for config in configs.values():
            node = config
            for part in path:
                node = (node or {}).get(part)
            values.append(json.dumps(node, sort_keys=True))
        assert len(set(values)) == len(values), (
            f"the examples share a {field}, so switching between them would not show it change")


def test_one_example_has_a_faq_and_another_does_not():
    """
    The only configuration difference that adds and removes a route.

    Everything else changes what a page shows. This changes whether a page exists, along with
    the navigation entry that links to it, and that is the behaviour most likely to be broken
    by a change nobody connected to it.
    """
    with_faq = []
    without = []
    for name in example_names():
        documents = branding_assets.content_documents(
            bundle_dir=os.path.join(EXAMPLES, name, branding_assets.ASSETS_DIRECTORY_NAME))
        (with_faq if any(d.startswith("faq") for d in documents) else without).append(name)

    assert with_faq, "no example publishes a FAQ, so the route appearing is never exercised"
    assert without, "every example publishes a FAQ, so the route disappearing is never exercised"


def test_every_asset_an_example_names_is_an_asset_it_ships():
    """
    The quietest way to get a kit wrong, and the only one a reader would blame themselves for.

    A logo URL in the configuration is resolved against the deployment's own bucket. If no
    file of that name was uploaded, the result is a broken image in the header of every page -
    no error, no log line, and nothing to connect it to a typo in a JSON file.
    """
    offenders = []
    for name in example_names():
        assets_dir = os.path.join(EXAMPLES, name, branding_assets.ASSETS_DIRECTORY_NAME)
        shipped = {os.path.relpath(path, assets_dir).replace(os.sep, "/")
                   for path in branding_assets.collect_assets(assets_dir)}
        config = example_config(name)
        branding = config.get("branding", {})

        referenced = list((branding.get("assets") or {}).values())
        referenced += [logo.get("src") for logo in (branding.get("partnerLogos") or [])]
        referenced += [(branding.get("seo") or {}).get("image")]
        referenced += list((branding.get("illustrations") or {}).values())

        for url in referenced:
            if not isinstance(url, str) or not url.startswith("/"):
                continue
            if url.lstrip("/") not in shipped:
                offenders.append(f"{name}: {url}")

    assert not offenders, (
        "these examples name a file they do not ship:\n"
        + "\n".join(f"    {o}" for o in sorted(offenders))
        + "\nThe URL resolves against the deployment's bucket, so the result is a broken "
          "image with nothing logged.")


def test_every_example_packs_into_an_assets_archive():
    """The archive is how the files travel, and it is where a disallowed type is caught."""
    for name in example_names():
        assets_dir = os.path.join(EXAMPLES, name, branding_assets.ASSETS_DIRECTORY_NAME)
        with tempfile.TemporaryDirectory() as workspace:
            size = branding_assets.pack_assets(assets_dir, os.path.join(workspace, "a.tar.gz"))
        assert size > 0, f"{name} packed to nothing"
        assert size <= branding_assets.MAX_ARCHIVE_BYTES, f"{name} is over the archive limit"


def test_every_example_document_is_in_a_language_that_example_offers():
    """
    The check a deployment makes, made here so a kit cannot ship a document nobody can reach.

    `content_documents` refuses a document written for a locale the deployment does not list,
    because a reader cannot select the language it is in. An example that failed this would
    fail on an operator's machine, at the end of the instructions it wrote itself.
    """
    for name in example_names():
        config = merged_config(name)
        documents = branding_assets.content_documents(
            bundle_dir=os.path.join(EXAMPLES, name, branding_assets.ASSETS_DIRECTORY_NAME),
            supported_locales=inject.derive_supported_locales(config))
        assert documents, f"{name} publishes no documents, so it shows the placeholder pages"


def test_every_example_merges_into_a_deployment_environment_file():
    """
    End to end on the path an operator actually takes: the example, the template, the env file.

    This is what caught the examples being written against a configuration shape the injector
    had stopped accepting - the same way a locale fixture was caught when language became one
    declaration instead of two.
    """
    from pathlib import Path
    known = inject.template_variables(Path(ENV_TEMPLATE))
    for name in example_names():
        with tempfile.TemporaryDirectory() as workspace:
            env_path = os.path.join(workspace, ".env.realm.dev")
            with open(env_path, "w", encoding="utf-8") as handle:
                handle.write("BACKEND_MONGODB_URI=mongodb://untouched\n")

            config = merged_config(name)
            inject.update_deployment_env(config, Path(env_path), Path(ENV_TEMPLATE))

            written = {}
            for line in open(env_path, encoding="utf-8"):
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    written[key.strip()] = value.rstrip("\n")

        assert written.get("BACKEND_MONGODB_URI") == "mongodb://untouched", (
            f"{name} disturbed an infrastructure value in the same file")
        assert written.get("GLOBAL_PRODUCT_NAME"), f"{name} wrote no product name"
        unknown = sorted(set(written) - known - {"BACKEND_MONGODB_URI"})
        assert not unknown, f"{name} wrote variables the deployment does not know: {unknown}"


def test_an_example_says_in_its_own_text_that_it_is_an_example():
    """
    These are legal documents by shape, and shape is what gets copied.

    A privacy policy names the organisation accountable for a reader's data. One of these
    that found its way into a real deployment would make a false statement to real users, so
    each says what it is inside itself, where a copy carries it along.
    """
    offenders = []
    for name in example_names():
        content_dir = os.path.join(EXAMPLES, name, branding_assets.ASSETS_DIRECTORY_NAME,
                                   branding_assets.CONTENT_DIRECTORY_NAME)
        if not os.path.isdir(content_dir):
            continue
        for document in sorted(os.listdir(content_dir)):
            text = open(os.path.join(content_dir, document), encoding="utf-8").read().lower()
            if "example" not in text and "ejemplo" not in text:
                offenders.append(f"{name}/{document}")
    assert not offenders, (
        "these example documents do not say they are examples:\n"
        + "\n".join(f"    {o}" for o in sorted(offenders)))


if __name__ == "__main__":
    _failed = 0
    for _name, _test in sorted(globals().items()):
        if not _name.startswith("test_") or not callable(_test):
            continue
        try:
            _test()
            print(f"ok   {_name}")
        except SystemExit as _e:
            _failed += 1
            print(f"FAIL {_name}: the injector refused and exited ({_e})")
        except Exception as _e:
            _failed += 1
            print(f"FAIL {_name}:\n  {_e}")
    print(f"\n{'FAILED' if _failed else 'OK'} - {_failed} failed")
    sys.exit(1 if _failed else 0)
