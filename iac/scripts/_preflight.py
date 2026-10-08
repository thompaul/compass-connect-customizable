"""
Checks that need the outside world, run before a deployment rather than during one.

The configuration checks in ``_common`` only read what was supplied. These open the
databases it names and look for the taxonomy model it points at — the two things the
application itself validates at startup, which in a container means a failed health check
several minutes into a deployment, after the service has been created.

Everything here is skippable, costs seconds, and never reports a credential.
"""

import os
import re
from typing import Any, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

#: The collection the taxonomy model's metadata lives in. Matches the application's
#: EmbeddingConfig default; if that is ever made configurable, this follows it.
TAXONOMY_MODEL_INFO_COLLECTION = "modelinfos"

#: Each database the application connects to, as the pair of variables naming it.
DATABASES: Tuple[Tuple[str, str], ...] = (
    ("TAXONOMY_MONGODB_URI", "TAXONOMY_DATABASE_NAME"),
    ("APPLICATION_MONGODB_URI", "APPLICATION_DATABASE_NAME"),
    ("USERDATA_MONGODB_URI", "USERDATA_DATABASE_NAME"),
    ("METRICS_MONGODB_URI", "METRICS_DATABASE_NAME"),
    ("CAREER_EXPLORER_MONGODB_URI", "CAREER_EXPLORER_DATABASE_NAME"),
    ("JOBS_MONGODB_URI", "JOBS_DATABASE_NAME"),
)

_DEFAULT_TIMEOUT_MS = 8000


def redact(uri: str) -> str:
    """
    A connection string with its password removed, safe to print.

    Pre-flight output goes to a terminal, a CI log and quite often a pasted bug report,
    so nothing here may carry a credential — including the exception text the driver
    raises, which repeats the whole URI.
    """
    try:
        parts = urlsplit(uri)
    except ValueError:
        return "<unparseable connection string>"
    if not parts.hostname:
        return "<connection string>"
    user = f"{parts.username}:***@" if parts.username else ""
    netloc = f"{user}{parts.hostname}" + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _scrub(message: str, uris: List[str]) -> str:
    """Remove any connection string, and any password, that leaked into a driver message."""
    for uri in uris:
        if uri:
            message = message.replace(uri, redact(uri))
    return re.sub(r"://([^:/@\s]+):[^@/\s]+@", r"://\1:***@", message)


def _load_driver():
    """
    Import the MongoDB driver only when a live check actually runs.

    Keeps ``--skip-validation`` and every offline use working without it installed, and
    turns a missing dependency into a sentence rather than an import error at startup.
    """
    try:
        from pymongo import MongoClient  # noqa: PLC0415 - deliberately deferred
        from bson import ObjectId  # noqa: PLC0415
        from bson.errors import InvalidId  # noqa: PLC0415
    except ImportError:
        return None
    return MongoClient, ObjectId, InvalidId


def check_databases(env: Mapping[str, str], *,
                    timeout_ms: int = _DEFAULT_TIMEOUT_MS) -> List[str]:
    """
    Open and authenticate every database the configuration names.

    A wrong password reaches the operator here, in seconds, instead of as a container
    that will not start. Distinct connection strings are tried once each, since several
    of these normally point at one cluster.
    """
    return probe_databases(env, timeout_ms=timeout_ms)[0]


def probe_databases(env: Mapping[str, str], *,
                    timeout_ms: int = _DEFAULT_TIMEOUT_MS) -> Tuple[List[str], set]:
    """
    As ``check_databases``, and also which connection strings could not be reached.

    The caller needs the second half to avoid asking an unreachable cluster a further
    question and reporting the same failure twice under a different name.
    """
    driver = _load_driver()
    if driver is None:
        return ["the MongoDB driver is not installed, so the databases were not checked - "
                "install it, or pass --skip-validation to accept the risk"], set()
    make_client = driver[0]

    problems: List[str] = []
    seen: dict = {}

    for uri_key, name_key in DATABASES:
        uri = (env.get(uri_key) or "").strip()
        database = (env.get(name_key) or "").strip()
        if not uri or not database:
            # Absent values are the template check's business, not this one's.
            continue

        if uri not in seen:
            seen[uri] = _try_connection(make_client, uri, timeout_ms)
            if seen[uri]:
                # One unreachable cluster, reported once however many variables name it.
                naming = [k for k, _ in DATABASES if (env.get(k) or "").strip() == uri]
                problems.append(
                    f"{redact(uri)} could not be reached: {seen[uri]}\n"
                    f"    named by {', '.join(naming)}")
        if seen[uri]:
            continue

        missing = _database_missing(make_client, uri, database, timeout_ms)
        if missing:
            problems.append(
                f"{name_key} is {database!r}, which {missing} on {redact(uri)}")

    return problems, {uri for uri, failure in seen.items() if failure}


def _try_connection(make_client, uri: str, timeout_ms: int) -> Optional[str]:
    """None if the connection authenticates, otherwise why it did not."""
    try:
        client = make_client(uri, serverSelectionTimeoutMS=timeout_ms)
        try:
            client.admin.command("ping")
        finally:
            client.close()
        return None
    except Exception as e:  # noqa: BLE001 - every failure is a finding, not a crash
        return _scrub(f"{type(e).__name__}: {e}", [uri])


def _database_missing(make_client, uri: str, database: str, timeout_ms: int) -> Optional[str]:
    """
    A description of the problem if the named database is not usable, otherwise None.

    An empty database is not an error — several of these are populated by the
    application on first run.
    """
    try:
        client = make_client(uri, serverSelectionTimeoutMS=timeout_ms)
        try:
            client[database].list_collection_names()
        finally:
            client.close()
        return None
    except Exception as e:  # noqa: BLE001
        return f"could not be read ({_scrub(f'{type(e).__name__}: {e}', [uri])})"


def check_taxonomy_model(env: Mapping[str, str], *,
                         timeout_ms: int = _DEFAULT_TIMEOUT_MS) -> List[str]:
    """
    Confirm the taxonomy model exists, and that its embeddings match this configuration.

    The application checks both at startup and refuses to serve if either fails. The
    second is the one worth catching early: embeddings generated by one model are not
    comparable with queries embedded by another, so a mismatch is not a degraded
    deployment but a broken one, and it is invisible until someone asks for a skills
    report.
    """
    uri = (env.get("TAXONOMY_MONGODB_URI") or "").strip()
    database = (env.get("TAXONOMY_DATABASE_NAME") or "").strip()
    model_id = (env.get("TAXONOMY_MODEL_ID") or "").strip()
    if not (uri and database and model_id):
        return []

    driver = _load_driver()
    if driver is None:
        return []  # the missing driver is already reported by check_databases
    make_client, object_id, _invalid_id = driver

    try:
        key = object_id(model_id)
    except Exception:  # noqa: BLE001 - the driver's own InvalidId, by any name
        return [f"TAXONOMY_MODEL_ID is {model_id!r}, which is not a valid identifier"]

    try:
        client = make_client(uri, serverSelectionTimeoutMS=timeout_ms)
        try:
            info = client[database][TAXONOMY_MODEL_INFO_COLLECTION].find_one({"modelId": {"$eq": key}})
        finally:
            client.close()
    except Exception as e:  # noqa: BLE001
        return [f"the taxonomy model could not be looked up: "
                f"{_scrub(f'{type(e).__name__}: {e}', [uri])}"]

    if info is None:
        return [f"TAXONOMY_MODEL_ID {model_id} is not in {TAXONOMY_MODEL_INFO_COLLECTION} "
                f"on {database} - the taxonomy may not have been imported into this database"]

    return _embeddings_mismatch(info, env)


def _embeddings_mismatch(info: Mapping[str, Any], env: Mapping[str, str]) -> List[str]:
    """Whether the stored embeddings were made by the model this deployment will query with."""
    service = info.get("embeddingsService") or {}
    stored_service = service.get("service_name")
    stored_model = service.get("model_name")
    if stored_service is None and stored_model is None:
        # The application warns and continues in this case, so this does too.
        return []

    wanted_service = (env.get("EMBEDDINGS_SERVICE_NAME") or "").strip()
    wanted_model = (env.get("EMBEDDINGS_MODEL_NAME") or "").strip()
    if stored_service == wanted_service and stored_model == wanted_model:
        return []

    return [
        f"the taxonomy embeddings were generated with {stored_service}/{stored_model} but "
        f"this deployment is configured for {wanted_service}/{wanted_model} - searches "
        f"would compare embeddings that are not comparable, so the application will refuse "
        f"to start. Either point at a taxonomy embedded with the configured model, or "
        f"configure the model the taxonomy was embedded with"
    ]


def run_live_checks(env: Mapping[str, str], *,
                    timeout_ms: int = _DEFAULT_TIMEOUT_MS) -> List[str]:
    """Every check that needs the outside world, as one list of problems."""
    problems, unreachable = probe_databases(env, timeout_ms=timeout_ms)

    # Looking the model up needs a working connection. Asking an unreachable cluster
    # anyway reports the same failure a second time, under a name that suggests a
    # different fault.
    taxonomy_uri = (env.get("TAXONOMY_MONGODB_URI") or "").strip()
    if taxonomy_uri not in unreachable:
        problems += check_taxonomy_model(env, timeout_ms=timeout_ms)
    return problems
