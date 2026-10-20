#!/usr/bin/env python3
"""
Publishing the product, and not changing what publishing already did.

The product's CI has always built these artifacts and uploaded them into a realm's own root
project. That is why a partner builds the product before deploying it: there is nowhere else
for it to come from. Making the destination an input is the whole of the change — one value,
defaulting to what every existing caller already gets.

The failure these guard against is the quiet one. If the default moves, every existing
deployment's next build goes somewhere it has never gone, and nobody finds out until a deploy
cannot find its artifacts. If one of the four is left out of a release, the same thing happens
later and in somebody else's deployment.

Runnable directly: `python3 test_publishing.py` from the iac directory.
"""
import os
import sys

import yaml

WORKFLOWS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".github", "workflows")

BUILD_WORKFLOWS = ["backend-ci.yml", "frontend-ci.yml", "admin-frontend-ci.yml", "config-ci.yml"]
PUBLISH = "publish-product.yml"


def _load(name: str) -> dict:
    with open(os.path.join(WORKFLOWS, name)) as f:
        return yaml.safe_load(f)


def _triggers(doc: dict) -> dict:
    """`on:` is parsed as the boolean True by YAML 1.1, which is a classic trap here."""
    return doc.get("on", doc.get(True, {})) or {}


def _text(name: str) -> str:
    return open(os.path.join(WORKFLOWS, name)).read()


def test_every_build_can_be_told_where_to_publish():
    for name in BUILD_WORKFLOWS:
        inputs = _triggers(_load(name)).get("workflow_call", {}).get("inputs", {})
        assert "artifacts-project" in inputs, (
            f"{name} cannot be told where to publish, so the product can only ever go to the "
            f"realm that built it")


def test_the_default_is_what_every_existing_caller_already_gets():
    """
    An empty default, falling back to the secret the workflows have always used. Anything else
    would move every existing deployment's artifacts on its next build.
    """
    for name in BUILD_WORKFLOWS:
        spec = _triggers(_load(name))["workflow_call"]["inputs"]["artifacts-project"]
        assert spec.get("required") is False, f"{name} now demands a destination from every caller"
        assert spec.get("default", "") == "", (
            f"{name} defaults to {spec.get('default')!r} rather than to the realm's own project")
        assert "inputs.artifacts-project || secrets.GCP_REALM_ROOT_PROJECT_ID" in _text(name), (
            f"{name} does not fall back to the project it has always published to")


def test_publishing_the_product_is_deliberate():
    """
    A release other people's deployments will pull is a decision. `main.yml` uploads on a push;
    this must not.
    """
    triggers = _triggers(_load(PUBLISH))
    assert "workflow_dispatch" in triggers, f"{PUBLISH} cannot be run on purpose"
    for automatic in ("push", "pull_request", "schedule"):
        assert automatic not in triggers, (
            f"{PUBLISH} publishes on {automatic}, so a release happens by accident")


def test_a_release_is_all_four_artifacts():
    """
    A deployment fetches image, both bundles and templates at one version. Three of four is not
    a release, and the failure surfaces later, in somebody else's deploy, as a missing artifact.
    """
    jobs = _load(PUBLISH)["jobs"]
    for part in ("backend", "frontend", "admin-frontend", "templates"):
        assert part in jobs, f"{PUBLISH} does not publish {part}"
    assert set(jobs["published"]["needs"]) >= {"backend", "frontend", "admin-frontend", "templates"}, (
        "the completion check does not wait for all four, so a partial release reports success")


def test_the_builds_are_reused_not_copied():
    """
    A second copy of a build is a second thing to keep correct, and the only difference that
    matters here is where the result is sent.
    """
    jobs = _load(PUBLISH)["jobs"]
    for part, workflow in [("backend", "backend-ci.yml"), ("frontend", "frontend-ci.yml"),
                           ("admin-frontend", "admin-frontend-ci.yml"),
                           ("templates", "config-ci.yml")]:
        uses = jobs[part].get("uses", "")
        assert uses.endswith(workflow), (
            f"{part} does not reuse {workflow}; it has its own copy of the build")


def test_the_destination_reaches_every_build():
    jobs = _load(PUBLISH)["jobs"]
    for part in ("backend", "frontend", "admin-frontend", "templates"):
        passed = (jobs[part].get("with") or {}).get("artifacts-project")
        assert passed and "inputs.artifacts-project" in str(passed), (
            f"{part} is published without the destination this run was given, so it goes to the "
            f"default while the others go to the product")



def test_the_publishing_credential_is_named_for_publishing():
    """
    The four builds authenticated with a secret named for an environment tier to write into a
    root project's Artifact Registry, which is neither a lower nor an upper environment. The
    name contradicted the job, and anyone setting it up had to be told to put one tier's key in
    a secret named for the other.
    """
    for name in BUILD_WORKFLOWS:
        text = _text(name)
        assert "GCP_ARTIFACTS_SERVICE_ACCOUNT_JSON" in text, (
            f"{name} authenticates with a credential named for an environment tier rather than "
            f"for what it does")
        assert "|| secrets.GCP_LOWER_ENVS_SERVICE_ACCOUNT_JSON" in text, (
            f"{name} no longer falls back to the old secret name, so a repository that has only "
            f"set that one stops publishing without being told why")


def test_no_workflow_names_an_organisation_it_does_not_own():
    """
    `deploy.yml` ran `pulumi org set-default tabiya-tech`, so every fork of this pipeline
    acted in that organisation's stacks with whatever access its token carried. The
    organisation a deploy acts in is the account it belongs to, not a value in a file.

    This is S2.1 — one of the patches a partner re-applies on every upgrade — reached through
    the pipeline rather than through the infrastructure code.
    """
    for name in sorted(os.listdir(WORKFLOWS)):
        if not name.endswith((".yml", ".yaml")):
            continue
        for line in _text(name).splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "org set-default tabiya" not in stripped, (
                f"{name} sets a Pulumi organisation by name:\n    {stripped}")


def test_the_deploy_refuses_rather_than_guessing_an_organisation():
    text = _text("deploy.yml")
    assert "vars.PULUMI_ORG" in text, (
        "deploy.yml does not read the organisation from a repository variable")
    assert "PULUMI_ORG is not set" in text, (
        "deploy.yml does not stop when no organisation is configured, so it would deploy "
        "into whichever one a default happened to name")


def test_the_deploy_does_not_demand_credentials_it_will_not_use():
    """
    AWS credentials are needed for one thing: NS records in a parent Route53 zone, which
    `iac/dns` creates only when `dns:delegation_provider` is "route53". The default is
    "none", so a deployment that delegates its DNS by hand declares no AWS resource at all.

    The step that configured those credentials was unconditional, so such a deployment
    failed before running a single deployment script - gated on access to an account it was
    never going to touch. The step must be skippable.
    """
    doc = _load("deploy.yml")
    steps = doc["jobs"]["deploy"]["steps"]

    configure = [s for s in steps if "configure-aws-credentials" in str(s.get("uses", ""))]
    assert len(configure) == 1, "expected exactly one AWS credential step in deploy.yml"
    assert configure[0].get("if"), (
        "the AWS credential step is unconditional, so a deployment that delegates its DNS "
        "by hand cannot deploy without credentials for a zone it never writes to")

    # The `secrets` context is not available in a step-level `if`, so a guard written the
    # obvious way silently evaluates to the empty string and skips the step always.
    assert "secrets." not in configure[0]["if"], (
        "the guard reads the `secrets` context, which GitHub does not provide to a "
        "step-level `if`; it would evaluate empty and skip the step even when credentials "
        "were supplied. Read the secret into a scoped `env` in an earlier step instead.")


def test_dns_delegation_defaults_to_not_touching_another_account():
    """The default must stay "none": the parent zone usually belongs to someone else."""
    dns_main = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "dns", "__main__.py")
    text = open(dns_main).read()
    assert 'getconfig("delegation_provider", default="none")' in text, (
        "iac/dns no longer defaults delegation_provider to 'none', so a deployment that "
        "sets nothing could try to write NS records into a zone it does not own")


def test_the_deploy_checks_out_the_product_not_whoever_called_it():
    """
    `actions/checkout` defaults to the repository that *started the run*. In a called
    workflow that is the caller, not the repository the workflow file came from - so a
    partner calling this workflow had it try to fetch the product's commit out of their own
    configuration repository:

        fatal: remote error: upload-pack: not our ref 9d0c9b12...

    The default is invisible here, where the caller and the product are the same repository.
    It is wrong for every other caller, which is every partner.
    """
    doc = _load("deploy.yml")
    steps = doc["jobs"]["deploy"]["steps"]
    checkout = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout")]
    assert checkout, "deploy.yml has no checkout step"

    named = checkout[0].get("with", {}).get("repository")
    assert named, (
        "the product checkout does not name a repository, so it takes the caller's - a "
        "partner's configuration repository, which does not contain the product")
    assert "inputs.product-repository" in str(named), (
        "the product checkout does not let a caller name the product repository, so only a "
        "caller that *is* the product repository can use this workflow")

    inputs = _triggers(doc).get("workflow_call", {}).get("inputs", {})
    assert "product-repository" in inputs, (
        "workflow_call does not accept product-repository, so a partner has no way to pass it")
    assert inputs["product-repository"].get("required") is not True, (
        "making product-repository required would break every existing caller, which is "
        "exactly the kind of change this input exists to avoid")


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
