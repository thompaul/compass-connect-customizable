#!/usr/bin/env python3
"""
Conditions checked before a module creates anything.

Both were learned by failing a live deployment. The delegation one let the authentication
module run for sixteen minutes against a verification that could never succeed; the
credential one failed in the backend after the Cloud Run service had been created, five
modules into a deployment that a user login had carried that far without complaint.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')))

from lib.preconditions import (
    MissingPrecondition,
    require_delegated_domain,
    require_service_account_credentials,
)

DOMAIN = "prod.beans.example.com"


class _Creds:
    def __init__(self, **attrs):
        for key, value in attrs.items():
            setattr(self, key, value)


def test_a_delegated_domain_passes():
    require_delegated_domain(DOMAIN, lookup=lambda _d: ["ns-cloud-a1.googledomains.com"])


def test_an_undelegated_domain_stops_before_anything_is_created():
    try:
        require_delegated_domain(DOMAIN, lookup=lambda _d: [])
    except MissingPrecondition as e:
        message = str(e)
    else:
        raise AssertionError("an undelegated domain must stop the module")
    assert DOMAIN in message, message
    assert "Nothing has been created" in message, message


def test_the_delegation_message_says_how_to_fix_it():
    """An operator who has never done this needs the command, not the concept."""
    try:
        require_delegated_domain(DOMAIN, lookup=lambda _d: [])
    except MissingPrecondition as e:
        message = str(e)
    assert "dns_name_servers" in message, "it must say where to get the nameservers"
    assert f"dig +short NS {DOMAIN}" in message, "it must say how to confirm the fix"
    assert "do not reuse an old record" in message, "the nameservers change on every rebuild"


def test_a_lookup_that_throws_is_treated_as_not_delegated():
    """A check must never be the thing that crashes a deployment."""
    def _explode(_domain):
        raise RuntimeError("no network")

    try:
        require_delegated_domain(DOMAIN, lookup=_explode)
    except MissingPrecondition:
        return
    except RuntimeError:
        raise AssertionError("a lookup failure must read as not delegated, not propagate")
    raise AssertionError("expected MissingPrecondition")


def test_service_account_credentials_pass():
    require_service_account_credentials(
        credentials=_Creds(service_account_email="ci@project.iam.gserviceaccount.com"))


def test_credentials_that_can_sign_pass_even_if_named_differently():
    """Impersonated credentials can mint the token too; accept by capability, not class."""
    require_service_account_credentials(
        credentials=_Creds(signer_email="ci@project.iam.gserviceaccount.com"))


def test_a_user_login_is_refused():
    try:
        require_service_account_credentials(credentials=_Creds(token="ya29...", quota_project_id="p"))
    except MissingPrecondition as e:
        message = str(e)
    else:
        raise AssertionError("a user login must be refused before anything is created")
    assert "GOOGLE_APPLICATION_CREDENTIALS" in message, "it must say what to set"
    assert "Nothing has been created" in message, message


def test_the_credential_message_explains_why_not_just_what():
    try:
        require_service_account_credentials(credentials=_Creds(token="ya29..."))
    except MissingPrecondition as e:
        message = str(e)
    assert "identity token" in message, "it must name the operation that needs it"
    assert "Cloud Run service has been created" in message, \
        "it must say what the alternative costs, which is why this check exists"


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
            print(f"FAIL {_name}: {_e}")
    print(f"\n{'FAILED' if _failed else 'OK'} - {_failed} failed")
    sys.exit(1 if _failed else 0)
