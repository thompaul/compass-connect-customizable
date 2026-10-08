import os
import sys

# Determine the absolute path to the 'iac' directory
libs_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
# Add this directory to sys.path,
# so that we can import the iac/lib module when we run pulumi from withing the iac/common directory.
sys.path.insert(0, libs_dir)

import pulumi
from deploy_dns import deploy_dns

from lib.std_pulumi import getconfig, getstackref, parse_realm_env_name_from_stack, load_dot_realm_env, get_stack_reference


def main():
    _, _, stack_name = parse_realm_env_name_from_stack()

    # Load environment variables.
    load_dot_realm_env(stack_name)

    # Get the config values
    location = getconfig("region", "gcp")
    # Delegation is manual by default: the parent zone is usually held by a different
    # team, in a different account, from the one running the deployment.
    delegation_provider = getconfig("delegation_provider", default="none")
    delegation_parent_zone = getconfig("delegation_parent_zone", default="")
    # Only needed to delegate in Route53; the AWS provider has no default region.
    aws_region = getconfig("region", "aws", default="")

    # Get stack reference for environment
    env_reference = get_stack_reference(module="environment", stack_name=stack_name)
    project = getstackref(env_reference, "project_id")
    domain_name = getstackref(env_reference, "domain_name")

    # Deploy common
    deploy_dns(
        project=project,
        location=location,
        domain_name=domain_name,
        delegation_provider=delegation_provider,
        delegation_parent_zone=delegation_parent_zone or None,
        aws_region=aws_region or None,
    )


if __name__ == "__main__":
    main()
