import pulumi
import pulumi_aws as aws

from lib.std_pulumi import get_resource_name


def _configure_ns_in_aws(parent_zone: str, sub_domain_name: pulumi.Output[str],
                         ns_records: pulumi.Output[list[str]]):
    """
    Deploy the NS records delegating the subdomain, in a Route53 parent zone.

    A manual escape hatch: this stack is not part of the deployment pipeline, and exists
    for delegating after the fact when the parent zone is in Route53 and reachable with
    the credentials to hand.
    """

    aws_zone = aws.route53.get_zone(name=parent_zone, private_zone=False)

    aws.route53.Record(
        get_resource_name(resource="subdomain", resource_type="ns-record"),
        zone_id=aws_zone.zone_id,
        name=sub_domain_name,
        type=aws.route53.RecordType.NS,
        ttl=300,
        records=ns_records
    )


def deploy_aws_ns(parent_zone: str, domain_name: pulumi.Output[str], ns_records: pulumi.Output[list[str]]):
    if not parent_zone:
        raise ValueError("dns:delegation_parent_zone is required to delegate in Route53")
    _configure_ns_in_aws(parent_zone, domain_name, ns_records)
