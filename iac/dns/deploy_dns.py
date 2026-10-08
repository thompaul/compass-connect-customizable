from typing import Optional, Sequence

import pulumi
import pulumi_gcp as gcp
import pulumi_aws as aws

from lib.std_pulumi import get_resource_name, ProjectBaseConfig, get_project_base_config, hash_string


def _get_zone_name(domain_name: str) -> str:
    # The zone name is a user assigned name for this resource.
    # Must be unique within the project.
    # The name must be 1-63 characters long, must begin with a letter, end with a letter or digit, and only contain lowercase letters, digits or dashes.
    # See https://cloud.google.com/dns/docs/reference/rest/v1/managedZones#resource:-managedzone

    # Generate a unique and predictable name for the zone
    _domain_name = domain_name.replace(".", "-")
    _hashed_domain_name = hash_string(domain_name)
    _prefix = "zone-"
    # ensure that the zone name is less than 63 characters and the has is completely included
    # We are removing the length of the connector, a dash (-) and the length of the prefix.
    _connector_length = 1  # the length of the dash (-) connector
    return f"{_prefix}{_domain_name[:63 - len(_prefix) - len(_hashed_domain_name) - _connector_length]}-{_hashed_domain_name}"


def _create_dns(*, basic_config: ProjectBaseConfig, domain_name: pulumi.Output[str]) -> gcp.dns.ManagedZone:
    # create sub domain in gcp
    dns_zone = gcp.dns.ManagedZone(get_resource_name(resource="dns", resource_type="zone"),
                                   name=domain_name.apply(lambda s: _get_zone_name(s)),
                                   dns_name=domain_name.apply(lambda _domain_name: f"{_domain_name}."),
                                   project=basic_config.project,
                                   opts=pulumi.ResourceOptions(provider=basic_config.provider))

    return dns_zone


def _delegate_in_route53(
        *,
        parent_zone: str,
        sub_domain_name: pulumi.Output[str],
        ns_records: pulumi.Output[Sequence[str]]) -> aws.route53.Record:
    """
    Create the NS records delegating this environment's subdomain, in a Route53 zone.

    Only reachable when dns:delegation_provider is set to "route53", because it needs
    AWS credentials with write access to the parent zone — which the deploying identity
    usually does not have. The parent zone is commonly held by a different team, in a
    different account, from the one running the deployment.
    """

    try:
        aws_zone = aws.route53.get_zone(name=parent_zone, private_zone=False)
    except Exception as e:  # noqa: BLE001 - re-raised with the context the provider lacks
        raise RuntimeError(
            f"Could not read the Route53 zone '{parent_zone}' to delegate the subdomain: {e}\n"
            f"  Delegating in Route53 needs AWS credentials with read and write access to that "
            f"zone, which is often held by a different team in a different account.\n"
            f"  To delegate by hand instead, set dns:delegation_provider to 'none'. The deploy "
            f"will then print the NS records to create."
        ) from e

    return aws.route53.Record(
        get_resource_name(resource="subdomain", resource_type="ns-record"),
        zone_id=aws_zone.zone_id,
        name=sub_domain_name,
        type=aws.route53.RecordType.NS,
        ttl=300,
        records=ns_records
    )


def _report_manual_delegation(domain_name: pulumi.Output[str],
                              ns_records: pulumi.Output[Sequence[str]]) -> None:
    """Print the records an operator has to create at their registrar."""

    def _report(args) -> None:
        _domain, _servers = args
        lines = "\n".join(f"      {s}" for s in _servers)
        pulumi.info(
            f"DNS delegation is manual (dns:delegation_provider is 'none').\n"
            f"    Create these NS records in the parent zone to delegate '{_domain}':\n"
            f"{lines}\n"
            f"    The managed certificate cannot be issued until they resolve."
        )

    pulumi.Output.all(domain_name, ns_records).apply(_report)


def _check_delegation_config(*, delegation_provider: str,
                             delegation_parent_zone: Optional[str],
                             aws_region: Optional[str]) -> None:
    """
    Check the delegation configuration before any resource is declared.

    The managed zone is created first, so a delegation problem found later leaves a zone
    behind and an environment that is neither delegated nor clean.
    """
    if delegation_provider == "none":
        return

    if delegation_provider != "route53":
        raise ValueError(
            f"Unsupported dns:delegation_provider {delegation_provider!r}. Supported: 'none', 'route53'."
        )

    missing = []
    if not delegation_parent_zone:
        missing.append("dns:delegation_parent_zone (the Route53 zone holding the parent domain)")
    if not aws_region:
        missing.append("aws:region (the AWS provider has no default)")
    if missing:
        raise ValueError(
            "dns:delegation_provider is 'route53', which also requires:\n"
            + "".join(f"  - {m}\n" for m in missing)
            + "  Set dns:delegation_provider to 'none' to delegate by hand instead."
        )


def deploy_dns(*,
               project: pulumi.Output[str],
               location: str,
               domain_name: pulumi.Output[str],
               delegation_provider: str = "none",
               delegation_parent_zone: Optional[str] = None,
               aws_region: Optional[str] = None):
    _check_delegation_config(delegation_provider=delegation_provider,
                             delegation_parent_zone=delegation_parent_zone,
                             aws_region=aws_region)

    basic_config = get_project_base_config(project=project, location=location)

    # Create the DNS
    dns_zone = _create_dns(basic_config=basic_config,
                           domain_name=domain_name)

    pulumi.export("dns_zone_id", dns_zone.id)
    pulumi.export("dns_zone_name", dns_zone.name)
    # Exported so the operator can read the values they need to delegate, without the
    # console. A rebuilt zone gets new nameservers, so this is needed on every cycle.
    pulumi.export("dns_name_servers", dns_zone.name_servers)

    # Already validated above, before anything was created.
    if delegation_provider == "none":
        _report_manual_delegation(domain_name, dns_zone.name_servers)
    else:
        _delegate_in_route53(parent_zone=delegation_parent_zone,
                             sub_domain_name=domain_name,
                             ns_records=dns_zone.name_servers)
