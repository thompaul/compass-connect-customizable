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

# The product's artifacts are resolved through one helper, which prefers the published
# repository and falls back to the realm's own. The deployment's own archive reads the realm
# output directly, because it is never anywhere else.
PRODUCT_CALL = "product_repository(realm_outputs)"
PARTNER_KEY = 'realm_outputs["generic_repository"]'


def _source(rel: str) -> str:
    return open(os.path.join(IAC, rel)).read()


def test_the_product_is_fetched_from_the_products_repository():
    for rel, what in PRODUCT_READERS.items():
        src = _source(rel)
        assert PRODUCT_CALL in src, (
            f"{rel} fetches {what} from the deployment's own repository, so this deployment "
            f"has to build the product before it can deploy it")


def test_the_deployments_own_files_stay_on_its_own_repository():
    """
    The archive is uploaded by the operator and downloaded by the same deployment. Sending it
    to the product's repository would need write access to the publisher's project, and would
    put one partner's logos where every other deployment looks.
    """
    upload = _source("scripts/setup_env.py")
    assert PARTNER_KEY in upload, (
        "setup_env.py no longer uploads the branding archive to the deployment's own "
        "repository")
    assert PRODUCT_CALL not in upload, (
        "setup_env.py uploads this deployment's branding to the product's repository")


def test_prepare_reads_both_and_keeps_them_apart():
    """The one file that touches both. It is the place they are most likely to be confused."""
    src = _source("scripts/prepare.py")
    assert PRODUCT_CALL in src, "prepare.py fetches no product artifacts"
    assert PARTNER_KEY in src, "prepare.py fetches no branding archive"


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



def test_a_realm_applied_before_this_branch_still_works():
    """
    The defect this was written for, found by deploying rather than reading.

    `product_generic_repository` and `product_docker_repository` only exist once the *realm*
    stack has been applied with the code that exports them. An environment is deployed far more
    often than its realm, so the first thing an existing deployment does after taking this
    branch is read an output that is not there:

        error: product_docker_repository is not set in the referenced stack

    before anything is built, about a stack output it has never heard of, and the realm it
    would have to re-apply is the one stack nobody wants to touch to get a frontend change out.

    The configuration default was written carefully - `gcp_product_artifacts_project` falls back
    to the realm's own project - and then the same care was not taken one layer up, at the stack
    reference. Both halves have to fall back for the branch to be safe to take.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "branding_assets", os.path.join(IAC, "lib", "branding_assets.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class _Output:
        def __init__(self, value): self.value = value

    own = {"name": "generic-repository", "location": "us-central1", "project": "realm-root"}
    published = {"name": "generic-repository", "location": "us-central1", "project": "publisher"}

    old_realm = {"generic_repository": _Output(own)}
    assert module.product_repository(old_realm) == own, (
        "a realm applied before this branch has no product repository and must fall back to "
        "its own; instead the deployment fails before it builds anything")

    new_realm = {"generic_repository": _Output(own),
                 "product_generic_repository": _Output(published)}
    assert module.product_repository(new_realm) == published, (
        "a realm that has been pointed at a published product is ignored")

    unset = {"generic_repository": _Output(own), "product_generic_repository": _Output(None)}
    assert module.product_repository(unset) == own, (
        "an export that exists but is empty is treated as a destination")


def test_the_docker_repository_falls_back_too():
    """The same fallback, in the stack that passes the image repository down."""
    source = _source("environment/__main__.py")
    assert 'get_output("product_docker_repository")' in source and \
           'get_output("docker_repository")' in source, (
        "the environment stack reads only one of the two, so either an old realm or a "
        "configured one is broken")
    assert "both[0] or both[1]" in source, (
        "the environment stack does not prefer the product repository and fall back to the "
        "realm's own")

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
