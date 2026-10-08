"""
Conditions a module needs before it declares a single resource.

Each of these was learned by failing: the deployment created resources, ran for minutes,
and then stopped on something that was knowable at the start. A precondition that raises
before anything exists costs seconds and leaves nothing behind.

The pattern follows ``dns/deploy_dns.py``: check first, raise with what to do about it.
"""

from typing import Any, Callable, List, Optional

__all__ = [
    "MissingPrecondition",
    "nameservers_for",
    "require_delegated_domain",
    "require_service_account_credentials",
]


class MissingPrecondition(Exception):
    """Something the module needs was not in place. Nothing has been created."""


def nameservers_for(domain: str, *, timeout: float = 10.0) -> List[str]:
    """
    The nameservers public DNS gives for a domain, or an empty list.

    An empty list means the domain is not delegated - which is indistinguishable, and
    equivalent, from not being resolvable at all for our purposes.
    """
    try:
        import dns.resolver  # noqa: PLC0415 - optional, and only this function needs it
    except ImportError:
        return []

    resolver = dns.resolver.Resolver()
    resolver.timeout = timeout
    resolver.lifetime = timeout
    try:
        answer = resolver.resolve(domain, "NS")
    except Exception:  # noqa: BLE001 - every failure means "not delegated"
        return []
    return sorted(str(record).rstrip(".") for record in answer)


def require_delegated_domain(domain: str, *,
                             lookup: Callable[[str], List[str]] = nameservers_for) -> None:
    """
    Refuse to continue until the environment's domain is delegated to its zone.

    Firebase proves ownership of the email domain by reading a TXT record from the
    environment's own DNS zone **over public DNS**. Until the parent zone delegates to it,
    that record is unreachable however correct it is, and the authentication module fails
    on a domain verification that can never succeed - after creating its DNS records, and
    after a long wait that looks like a transient fault rather than a missing step.

    The runbook used to list delegation as a post-deployment step for the certificate's
    sake. The certificate belongs to the last module; this is needed four modules earlier.
    """
    try:
        delegated = lookup(domain)
    except Exception:  # noqa: BLE001 - a check must never be the thing that crashes
        delegated = []
    if delegated:
        return

    raise MissingPrecondition(
        f"'{domain}' is not delegated, so nothing can read its DNS records.\n"
        f"\n"
        f"  Authentication proves ownership of this domain by reading a TXT record from\n"
        f"  the environment's DNS zone over public DNS. Until the parent zone delegates\n"
        f"  to it, that lookup fails however correct the record is.\n"
        f"\n"
        f"  Deploy the dns module first, then create an NS record for '{domain}' in the\n"
        f"  parent zone using the nameservers it exports:\n"
        f"\n"
        f"      cd iac/dns && pulumi stack output dns_name_servers\n"
        f"\n"
        f"  They change every time the zone is recreated, so do not reuse an old record.\n"
        f"  Confirm with: dig +short NS {domain}\n"
        f"\n"
        f"Nothing has been created."
    )


def require_service_account_credentials(*, credentials: Optional[Any] = None) -> None:
    """
    Refuse to continue unless the credentials in force are a service account.

    The API gateway configuration is built by fetching an identity token for the Cloud Run
    service, and that fetch works only with a service account key or the metadata server -
    never with the credentials ``gcloud auth application-default login`` writes. A user
    login carries a deployment through five modules and then fails here, **after the Cloud
    Run service has been created**, as

        DefaultCredentialsError: Neither metadata server or valid service account
        credentials are found.

    which reads as a configuration fault rather than as the wrong kind of login.
    """
    if credentials is None:
        try:
            import google.auth  # noqa: PLC0415
            credentials, _project = google.auth.default()
        except Exception as e:  # noqa: BLE001
            raise MissingPrecondition(
                f"No Google credentials are available: {type(e).__name__}: {e}\n"
                f"Nothing has been created."
            ) from e

    if _is_service_account(credentials):
        return

    raise MissingPrecondition(
        "This module needs service account credentials, and the ones in force are not.\n"
        "\n"
        "  Building the API gateway configuration fetches an identity token for the Cloud\n"
        "  Run service. That is only possible with a service account key or from inside\n"
        "  Google's infrastructure - a user login cannot do it, and fails only after the\n"
        "  Cloud Run service has been created.\n"
        "\n"
        "  Point GOOGLE_APPLICATION_CREDENTIALS at the realm's CI/CD service account key:\n"
        "\n"
        "      export GOOGLE_APPLICATION_CREDENTIALS=/path/to/<realm>-upper-env-ci-cd-key.json\n"
        "\n"
        "  Note that this also changes the active gcloud account for the session.\n"
        "\n"
        "Nothing has been created."
    )


def _is_service_account(credentials: Any) -> bool:
    """
    Whether these credentials can mint an identity token without a metadata server.

    Checked by capability rather than by class, so impersonated and signing credentials
    that can also do it are accepted.
    """
    if getattr(credentials, "service_account_email", None):
        return True
    # Credentials read from a key file carry the signer's email; user credentials do not.
    return getattr(credentials, "signer_email", None) is not None
