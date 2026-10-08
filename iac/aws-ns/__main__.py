import os
import sys

# Determine the absolute path to the 'iac' directory
libs_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
# Add this directory to sys.path,
# so that we can import the iac/lib module when we run pulumi from withing the iac/aws-ns directory.
sys.path.insert(0, libs_dir)

import pulumi
from deploy_aws_ns import deploy_aws_ns

from lib.std_pulumi import parse_realm_env_name_from_stack, getstackref, load_dot_realm_env, get_stack_reference, getconfig


def main():
    _, _, stack_name = parse_realm_env_name_from_stack()

    # Load environment variables
    load_dot_realm_env(stack_name)

    # get stack reference to the environment
    env_reference = get_stack_reference(module="environment", stack_name=stack_name)
    domain_name = getstackref(env_reference, "domain_name")

    # get stack reference to the common stack
    common_stack_ref = get_stack_reference(module="common", stack_name=stack_name)
    ns_records = getstackref(common_stack_ref, "ns-records")

    # The Route53 zone holding the parent domain.
    parent_zone = getconfig("delegation_parent_zone", "dns", default="")

    # Deploy the aws ns
    deploy_aws_ns(
        parent_zone,
        domain_name,
        ns_records
    )


if __name__ == "__main__":
    main()
