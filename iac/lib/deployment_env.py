"""
A deployment's environment, assembled from the part that can be committed and the part that
cannot.

A deployment's configuration has always been one file holding two different things: settings
an operator edits - product name, locales, feature flags, limits - and credentials they must
protect. Because they share a file, the file inherits the stricter rule, so none of it can go
in a repository. That is why a partner cannot own their own configuration today: there is
nothing committable to own.

This module separates them. The product declares which names are credentials, in
`templates/secret-variables.txt`; everything else is ordinary configuration. The committable
file holds the configuration, and the credentials arrive from a secrets file or from the
environment, so continuous integration can inject them without either ever being written down
next to the other.

Nothing here reads or logs a value. The names are enough to do the work, and a module that
assembles credentials is the last place that should be holding them in a message.
"""
import os
import re
from typing import Dict, List, Tuple

_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def declared_secret_names(templates_dir: str) -> List[str]:
    """The variables the product considers credentials, in the order it declares them."""
    path = os.path.join(templates_dir, "secret-variables.txt")
    names = []
    with open(path, encoding="utf-8") as declaration:
        for line in declaration:
            line = line.strip()
            if line and not line.startswith("#"):
                names.append(line)
    return names


def parse_env(path: str) -> Dict[str, str]:
    """
    The assignments in an env file, as names to values.

    **A value can span lines.** This deployment's RSA encryption key is a PEM block of nine
    lines inside double quotes, and a line-based reader silently keeps the first line and
    discards the rest - producing a truncated private key and a file that no longer parses.
    That is not a hypothetical: it is what the first version of this function did, and the
    round-trip test did not catch it because it compared two dictionaries built by this same
    reader, so both sides lost the same eight lines and matched perfectly.

    So the rule is: if a value opens with a quote and does not close it on the same line, the
    following lines belong to it until the closing quote. Everything else is one line, as
    before.
    """
    values: Dict[str, str] = {}
    pending_name = None
    pending_lines: List[str] = []
    quote = ""

    with open(path, encoding="utf-8") as env_file:
        for raw in env_file:
            line = raw.rstrip("\n")

            if pending_name is not None:
                pending_lines.append(line)
                if line.rstrip().endswith(quote):
                    values[pending_name] = "\n".join(pending_lines)
                    pending_name, pending_lines, quote = None, [], ""
                continue

            if not line.strip() or line.lstrip().startswith("#"):
                continue

            match = _ASSIGNMENT.match(line.lstrip())
            if not match:
                continue

            name, value = match.group(1), match.group(2)
            opening = value[:1]
            if opening in ('"', "'") and not (len(value) > 1 and value.rstrip().endswith(opening)):
                # Opens a quote it does not close: the value continues on the next line.
                pending_name, pending_lines, quote = name, [value], opening
            else:
                values[name] = value

    if pending_name is not None:
        # An unterminated quote. Keeping what there is would write a truncated credential into
        # a deployment, which is the failure this function exists to prevent.
        raise ValueError(
            f"{path}: the value of {pending_name} opens with {quote} and never closes it, so "
            f"it cannot be read without guessing where it ends")

    return values


def required_secret_names(templates_dir: str) -> List[str]:
    """
    The credentials a deployment cannot do without.

    Declared-secret and required are different things, and conflating them was a mistake worth
    recording: this deployment supports more than one LLM provider and more than one optional
    service, so `ANTHROPIC_API_KEY` and `MATCHING_SERVICE_API_KEY` are credentials that a
    deployment using Gemini and no matching service correctly leaves empty. Demanding them
    would refuse to deploy a configuration that is right.

    Requiredness is read from the template rather than declared a second time, because the
    template already says it: a value between slashes is a regex the real value must match,
    with `/.*/` meaning optional, and anything else is required.
    """
    template = os.path.join(templates_dir, "env.template")
    optional = set()
    with open(template, encoding="utf-8") as lines:
        for line in lines:
            match = _ASSIGNMENT.match(line.strip())
            if match and match.group(2).startswith("/") and match.group(2).endswith("/"):
                optional.add(match.group(1))
    return [name for name in declared_secret_names(templates_dir) if name not in optional]


def secrets_in(values: Dict[str, str], secret_names: List[str]) -> List[str]:
    """Which declared credentials appear in this file, named but never valued."""
    return [name for name in secret_names if name in values]


def assemble(*, config_values: Dict[str, str], secret_values: Dict[str, str],
             environment: Dict[str, str], secret_names: List[str],
             required_names: List[str]) -> Tuple[Dict[str, str], List[str]]:
    """
    One environment from the two halves, and the required credentials that are still missing.

    Secrets are taken from the secrets file first and the process environment second, so a
    pipeline can inject what a file does not carry. A credential still sitting in the
    committable half is honoured last, so that a deployment mid-migration keeps working - and
    `secrets_in` reports it separately, because the file it is in is the one about to be
    committed.

    An empty value is a decision, not an absence. A deployment that uses Gemini sets
    `ANTHROPIC_API_KEY` to nothing on purpose, and carrying the empty value through is what
    makes the assembled environment identical to the one it replaces.

    Returns the environment and the names with nowhere to come from, rather than raising, so
    an operator setting a deployment up is told about all of them at once rather than one per
    attempt.
    """
    assembled = dict(config_values)
    missing: List[str] = []
    required = set(required_names)

    for name in secret_names:
        if name in secret_values:
            assembled[name] = secret_values[name]
        elif environment.get(name):
            assembled[name] = environment[name]
        elif name in config_values:
            assembled[name] = config_values[name]
        elif name in required:
            missing.append(name)

    # A required credential that is present and empty is as absent as one that is not there.
    missing.extend(name for name in secret_names
                   if name in required and name not in missing and not assembled.get(name))

    return assembled, missing


def _rendered(name: str, value: str) -> str:
    """
    One value, quoted if it has to be to survive being written and read back.

    A value read from a file arrives with its quotes still attached - `parse_env` keeps them -
    so writing `NAME=value` restores exactly what was there, and re-quoting would change bytes
    something downstream parses.

    **A value injected as an environment variable has no quotes**, because environment
    variables have no quoting convention. For a credential that spans lines - this deployment's
    RSA key is a nine-line PEM block - writing it unquoted produces a file where the eight
    remaining lines each read as a new assignment:

        warning: env.MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAwLurLSHCHirJtYfbPD1k
                 is not in the template configuration

    This is the same defect as the one `parse_env` documents, arriving from the other side: it
    dropped lines on the way in, and this dropped them on the way out. The round trip hid it
    both times, because a file written unquoted and read by a reader that expects quotes fails
    somewhere else entirely - in a validator, against a template, naming base64 as a key.
    """
    if "\n" not in value:
        return value
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value
    if '"' not in value:
        return f'"{value}"'
    if "'" not in value:
        return f"'{value}'"
    raise ValueError(
        f"{name} spans lines and contains both kinds of quote, so it cannot be written to an "
        f"env file without an escaping convention this format does not have.")


def render_env(values: Dict[str, str]) -> str:
    """
    The assembled environment, in the form the rest of the deployment already reads.
    """
    return "".join(f"{name}={_rendered(name, value)}\n" for name, value in values.items())
