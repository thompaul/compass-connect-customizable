import json
import os
import sys

# Determine the absolute path to the 'iac' directory
libs_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
# Add this directory to sys.path,
# so that we can import the iac/lib module when we run pulumi from withing the iac/auth directory
sys.path.insert(0, libs_dir)

import pulumi
from setup_identity_platform import deploy_auth

from lib.std_pulumi import load_dot_realm_env, getenv, getstackref, getconfig, parse_realm_env_name_from_stack, get_stack_reference


def main():
    _, _, stack_name = parse_realm_env_name_from_stack()
    # Load environment variables
    load_dot_realm_env(stack_name)

    # get the config values
    location = getconfig(name="region", config="gcp")
    app_name = getconfig(name="app_name")

    # Get stack reference for environment
    env_reference = get_stack_reference(module="environment", stack_name=stack_name)
    environment_type = getstackref(env_reference, "environment_type")
    project_id = getstackref(env_reference, "project_id")
    domain_name = getstackref(env_reference, "domain_name")
    auth_domain = getstackref(env_reference, "auth_domain")
    frontend_domain = getstackref(env_reference, "frontend_domain")

    # Get stack reference for dns
    dns_stack_ref = get_stack_reference(module="dns", stack_name=stack_name)
    dns_zone_name = getstackref(dns_stack_ref, "dns_zone_name")

    # Get environment variables
    # Secrets are not stored in the pulumi state file but in the .env file
    gcp_oauth_client_id = getenv("GCP_OAUTH_CLIENT_ID")
    gcp_oauth_client_secret = getenv("GCP_OAUTH_CLIENT_SECRET", secret=True)

    # Vanity domains this deployment is reached at, beyond the generated one.
    # e.g. FRONTEND_CUSTOM_DOMAINS='["example.org"]' ADMIN_FRONTEND_CUSTOM_DOMAINS='["admin.example.org"]'
    _extra_frontend = os.getenv("FRONTEND_CUSTOM_DOMAINS")
    _extra_admin = os.getenv("ADMIN_FRONTEND_CUSTOM_DOMAINS")
    frontend_custom_domains = json.loads(_extra_frontend) if _extra_frontend else []
    extra_authorized_domains = (
        frontend_custom_domains +
        (json.loads(_extra_admin) if _extra_admin else [])
    )
    # The first is canonical: it is the one Firebase puts in its sign-in emails and in the
    # link that completes a password reset, so it has to be the address the user typed.
    custom_domain = frontend_custom_domains[0] if frontend_custom_domains else None

    # Deploy the auth
    deploy_auth(
        location=location,
        environment_type=environment_type,
        project=project_id,
        dns_zone_name=dns_zone_name,
        domain_name=domain_name,
        auth_domain=auth_domain,
        frontend_domain=frontend_domain,
        extra_authorized_domains=extra_authorized_domains,
        gcp_oauth_client_id=gcp_oauth_client_id,
        gcp_oauth_client_secret=gcp_oauth_client_secret,
        app_name=app_name,
        custom_domain=custom_domain,
    )


if __name__ == "__main__":
    main()
