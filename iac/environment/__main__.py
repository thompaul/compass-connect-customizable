import os
import sys

from env_types import EnvironmentTypes

# Determine the absolute path to the 'iac' directory
libs_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
# Add this directory to sys.path,
# so that we can import the iac/lib module when we run pulumi from withing the iac/environment directory
sys.path.insert(0, libs_dir)

import pulumi
from lib import getconfig, getstackref, parse_realm_env_name_from_stack, get_stack_reference
from create_new_environment import create_new_environment


def main():
    realm_name, environment_name, _ = parse_realm_env_name_from_stack()

    # Get the config values
    gcp_region = getconfig("region", "gcp")

    environment_type: EnvironmentTypes = EnvironmentTypes(getconfig("environment_type"))
    # check that it is one of the allowed values
    if environment_type not in EnvironmentTypes:
        raise ValueError(f"environment_type {environment_type} is not allowed. Allowed values are {EnvironmentTypes}")

    pulumi.info(f'Creating environment:{environment_name} with type:{environment_type} in realm:{realm_name}')

    # Get realm stack references
    realm_reference = get_stack_reference(module="realm", stack_name=realm_name)

    billing_account = getstackref(realm_reference, "billing_account_id", True)
    root_project_id = getstackref(realm_reference, "root_project_id")
    # The image the backend runs is the product. It comes from wherever the realm says the
    # product is published, falling back to the realm's own repository.
    #
    # The fallback is not decoration. `product_docker_repository` only exists once the realm
    # stack has been applied with the code that exports it, and an environment is deployed far
    # more often than its realm. Without this, every existing deployment taking this branch
    # fails here, before anything is built, with a message about a stack output it has never
    # heard of - and the realm it would have to re-apply is the one stack nobody wants to touch
    # to get a frontend change out.
    docker_repository = pulumi.Output.all(
        realm_reference.get_output("product_docker_repository"),
        realm_reference.get_output("docker_repository"),
    ).apply(lambda both: both[0] or both[1])
    base_domain_name = getstackref(realm_reference, "base_domain_name")

    # if the environment is prod, use the compass upper folder, otherwise use the compass lower folder
    if environment_type == EnvironmentTypes.PROD:
        folder_id = getstackref(realm_reference, "upper_env_folder_id")
    else:
        folder_id = getstackref(realm_reference, "lower_env_folder_id")

    # export realm values to simplify the stack references downstream
    pulumi.export("realm_name", realm_name)
    pulumi.export("root_project_id", root_project_id)
    pulumi.export("docker_repository", docker_repository)
    pulumi.export("environment_type", environment_type.value)
    # DOMAIN_NAME=<ENVIRONMENT_NAME>.<REALM_NAME>.<BASE_DOMAIN_NAME>
    domain_name = base_domain_name.apply(lambda _base_domain_name: f"{environment_name}.{realm_name}.{_base_domain_name}")

    pulumi.export("domain_name", domain_name)
    # We need to set up the frontend and backend URLs here, and not in the fronend and backend iac projects as we would have liked, so that:
    #   a) to ensure that they do not conflict with each other
    #   b) to ensure that the frontend URL is available for both the frontend and also the auth iac project
    #   c) to ensure that the frontend URL is available for the backend iac project to set up the CORS policy
    pulumi.export("frontend_domain", domain_name)
    pulumi.export("frontend_url", domain_name.apply(lambda _domain_name: f"https://{_domain_name}"))

    pulumi.export("backend_domain", domain_name)
    pulumi.export("backend_url", domain_name.apply(lambda _domain_name: f"https://{_domain_name}/api"))

    pulumi.export("auth_domain", domain_name.apply(lambda _domain_name: f"auth.{_domain_name}"))

    # Admin frontend domain: admin.<env-name>.<realm-name>.<base-domain>
    pulumi.export("admin_frontend_domain", domain_name.apply(lambda _domain_name: f"admin.{_domain_name}"))
    pulumi.export("admin_frontend_url", domain_name.apply(lambda _domain_name: f"https://admin.{_domain_name}"))

    create_new_environment(
        realm_name=realm_name,
        region=gcp_region,
        folder_id=folder_id,
        billing_account=billing_account,
        environment_name=environment_name
    )


if __name__ == "__main__":
    main()
