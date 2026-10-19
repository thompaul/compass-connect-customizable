#!/usr/bin/env python3
"""
Two kinds of artifact travel through this deployment and they have different owners.

The container image and the two frontend bundles are the **product**. Tabiya builds them and
every deployment runs the same bytes. The branding archive is the **deployment's own**: its
operator builds it from their `assets/` directory and nobody else has a copy.

Until these were separated both came out of the realm's own repositories, which is why a
partner had to build the product themselves — there was nowhere else for it to come from. The
separation is what lets a deployment run an image it did not build while still supplying its
own logos.

The failure this guards against is quiet: pointing the branding archive at the product's
repository would make every deployment wear the publisher's marks, and pointing the product at
the partner's would make them build it again. Neither fails loudly. The first looks like
branding that did not apply; the second looks like a slow deploy.

Read from source rather than executed, because running these modules needs pulumi and a realm.

Runnable directly: `python3 test_artifact_sources.py` from the iac directory.
"""
import ast
import os
import sys

IAC = os.path.dirname(os.path.abspath(__file__))

# Who reads which repository, and why.
PRODUCT_READERS = {
    "scripts/prepare.py": "the env and stack-config templates",
    "frontend/prepare_frontend.py": "the frontend bundle",
    "admin_frontend/prepare_admin_frontend.py": "the admin frontend bundle",
}
PARTNER_READERS = {
    "scripts/setup_env.py": "uploads this deployment's branding archive",
    "scripts/prepare.py": "downloads this deployment's branding archive",
}

PRODUCT_KEY = '"product_generic_repository"'
PARTNER_KEY = '"generic_repository"'


def _source(rel: str) -> str:
    return open(os.path.join(IAC, rel)).read()


def test_the_product_is_fetched_from_the_products_repository():
    for rel, what in PRODUCT_READERS.items():
        src = _source(rel)
        assert f'realm_outputs[{PRODUCT_KEY}]' in src, (
            f"{rel} fetches {what} from the deployment's own repository, so this deployment "
            f"has to build the product before it can deploy it")


def test_the_deployments_own_files_stay_on_its_own_repository():
    """
    The archive is uploaded by the operator and downloaded by the same deployment. Sending it
    to the product's repository would need write access to the publisher's project, and would
    put one partner's logos where every other deployment looks.
    """
    upload = _source("scripts/setup_env.py")
    assert f'realm_outputs[{PARTNER_KEY}]' in upload, (
        "setup_env.py no longer uploads the branding archive to the deployment's own "
        "repository")
    assert PRODUCT_KEY not in upload, (
        "setup_env.py uploads this deployment's branding to the product's repository")


def test_prepare_reads_both_and_keeps_them_apart():
    """The one file that touches both. It is the place they are most likely to be confused."""
    src = _source("scripts/prepare.py")
    assert f'realm_outputs[{PRODUCT_KEY}]' in src, "prepare.py fetches no product artifacts"
    assert f'realm_outputs[{PARTNER_KEY}]' in src, "prepare.py fetches no branding archive"


def test_the_realm_publishes_where_the_product_comes_from():
    src = _source("realm/create_realm.py")
    for export in ("product_generic_repository", "product_docker_repository",
                   "product_artifacts_are_external"):
        assert f'pulumi.export("{export}"' in src, (
            f"the realm no longer exports {export}, so downstream stacks cannot tell where the "
            f"product is published")
    assert 'getconfig(\n        "gcp_product_artifacts_project"' in src or \
           'getconfig("gcp_product_artifacts_project"' in src, (
        "the product's project is no longer configurable, so a realm cannot be pointed at a "
        "published product")


def test_a_realm_that_configures_nothing_behaves_as_before():
    """
    The default has to be the realm's own project. Anything else would change what every
    existing deployment does on its next apply.
    """
    src = _source("realm/create_realm.py")
    assert "default=root_project_id" in src, (
        "the product's project no longer defaults to the realm's own, so an existing "
        "deployment would start pulling from somewhere it has never pulled from")


def test_the_reader_grant_is_skipped_only_for_a_repository_we_do_not_own():
    """
    Granting read access is a write to the repository's IAM policy. Correct on our own
    repository, impossible on the publisher's.
    """
    src = _source("backend/deploy_backend.py")
    assert "if product_artifacts_are_external:" in src, (
        "the backend grants itself read access unconditionally, which fails on a repository "
        "owned by somebody else")
    assert "membership = None" in src, "the skipped branch does not define membership"
    assert "if d is not None" in src, (
        "the dependency list does not tolerate a skipped grant, so the deploy fails with a "
        "None in it")


def test_the_flag_is_a_plain_value_not_an_output():
    """
    A pulumi Output is truthy whatever it wraps, so reading this through a stack reference
    would take the same branch either way — and the resource it governs cannot be created
    inside an `.apply()`.
    """
    src = _source("backend/__main__.py")
    assert 'getstackref(env_reference, "product_artifacts_are_external")' not in src, (
        "the flag is read as a stack reference, which is an Output and always truthy")
    assert 'getconfig(\n        "product_artifacts_are_external"' in src or \
           'getconfig("product_artifacts_are_external"' in src, (
        "the flag is not read from this stack's configuration")


def test_the_template_tells_an_operator_the_setting_exists():
    template = _source("templates/stack_config.template.yaml")
    assert "product_artifacts_are_external" in template, (
        "an operator pointing a realm at a published product has no way to learn that this "
        "setting exists")


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
