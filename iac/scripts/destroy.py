#!/usr/bin/env python3

import os

import argparse
import sys

# Determine the absolute path to the 'iac' directory
iac_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
# Add this directory to sys.path,
# so that we can import the iac/lib module when we run pulumi from withing the iac/scripts directory.
sys.path.insert(0, iac_dir)

from _types import IaCModules, DESTROY_ORDER
from lib import get_stack_name_from, load_dot_realm_env
from _common import add_select_environment_arguments, destroy_with_retry, \
    get_protected_resources, unprotect_resources

DESTROYED = "destroyed"
FAILED = "failed"
SKIPPED = "not attempted"


def find_protected_resources(stack_name: str) -> dict:
    """Collect the protected resources of every module, before anything is destroyed."""
    found = {}
    for module in DESTROY_ORDER:
        protected = get_protected_resources(stack_name, module)
        if protected:
            found[module] = protected
    return found


def _report_protected(stack_name: str, *, delete_protected: bool) -> bool:
    """
    Report resources that are protected, before anything is destroyed.

    Returns True if the teardown may proceed.
    """
    found = find_protected_resources(stack_name)
    if not found:
        return True

    print("\nProtected resources in this environment:\n")
    for module, resources in found.items():
        for resource in resources:
            print(f"  {module.value:16s} {resource['type']}")
            print(f"  {'':16s} {resource['urn']}")
    print()

    if not delete_protected:
        print(
            "These are protected deliberately — they hold data that should not disappear\n"
            "with a teardown. Nothing has been destroyed.\n\n"
            "Decide what should happen to the data they hold, including any retention\n"
            "obligations, then either:\n"
            "  - re-run with --delete-protected to remove them along with everything else, or\n"
            "  - remove them from the stack by hand and re-run to destroy the rest.\n"
        )
        return False

    print("--delete-protected given: clearing protection so these will be destroyed.\n")
    for module, resources in found.items():
        unprotect_resources(stack_name, module, [r["urn"] for r in resources])
    return True


def destroy_stack(stack_name: str, *, stop_on_error: bool = False) -> dict:
    """
    Destroy every module of the environment, in the reverse of the order they are created.

    A module that fails does not stop the ones that follow: several of them are
    independent, and an operator learns more from one run that reports everything than
    from several that each stop at the first problem. Re-running resumes, because
    destroying an already-empty stack is a no-op.
    """
    print(f"Destroying stack: {stack_name}")
    results = {}
    stopped = False

    for module in DESTROY_ORDER:
        if stopped:
            results[module] = SKIPPED
            continue
        try:
            destroy_with_retry(stack_name, module)
            results[module] = DESTROYED
        except Exception as e:  # noqa: BLE001 - recorded and reported in the summary
            print(f"\n  {module.value} failed: {e}\n")
            results[module] = FAILED
            stopped = stop_on_error

    return results


def _print_summary(stack_name: str, results: dict) -> bool:
    print(f"\n{'=' * 60}")
    print(f"Teardown summary: {stack_name}")
    print(f"{'=' * 60}")
    for module in DESTROY_ORDER:
        print(f"  {module.value:18s} {results.get(module, SKIPPED)}")

    failed = [m.value for m, r in results.items() if r == FAILED]
    skipped = [m.value for m, r in results.items() if r == SKIPPED]
    print()
    if not failed and not skipped:
        print("Every module destroyed. Nothing is left to bill for.")
        return True

    if failed:
        print(f"Failed: {', '.join(failed)}")
    if skipped:
        print(f"Not attempted: {', '.join(skipped)}")
    print("\nThe environment is partly torn down. Re-run to resume — modules already\n"
          "destroyed are a no-op.")
    return False


def _main(*, realm_name: str, env_name: str, delete_protected: bool, stop_on_error: bool):
    # 1. Get the stack name from the realm name and environment name.
    stack_name = get_stack_name_from(realm_name, env_name)

    # 2. Load the environment variables for this stack, as the deploy path does. Provider
    #    configuration is read from here, not only from the stack config.
    load_dot_realm_env(stack_name)

    # 3. Surface anything protected before destroying, so it is a decision rather than an
    #    error met partway through.
    if not _report_protected(stack_name, delete_protected=delete_protected):
        sys.exit(2)

    # 4. Destroy the stack.
    results = destroy_stack(stack_name, stop_on_error=stop_on_error)

    # 5. Report, and exit non-zero if anything is left.
    if not _print_summary(stack_name, results):
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Destroy the given environment by running pulumi destroy on all the stacks of the environment."
    )

    # add the required arguments to select the environment to set up.
    add_select_environment_arguments(parser=parser)
    parser.add_argument(
        "--delete-protected", action="store_true",
        help="Also destroy resources marked protected. These hold data that is kept "
             "deliberately; read what the teardown reports about them first."
    )
    parser.add_argument(
        "--stop-on-error", action="store_true",
        help="Stop at the first module that fails, instead of attempting the rest."
    )

    args = parser.parse_args()
    _main(realm_name=args.realm_name, env_name=args.env_name,
          delete_protected=args.delete_protected, stop_on_error=args.stop_on_error)
