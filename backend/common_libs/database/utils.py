import asyncio
import logging
import math
import os
import re
import time
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ConnectionFailure

# How long one attempt to reach a database is given, and how far apart the attempts are.
#
# Measured rather than guessed. On a Cloud Run cold start against Atlas, a ping that is going
# to succeed is answered in about 250ms, and the four databases after it share the connection
# and are up about 20ms later. A ping that is going to fail does not take somewhat longer than
# that: it runs to the end of whatever budget it is given, because the connection is not slow,
# it is absent. Nothing in between has been observed.
#
# So a long timeout buys nothing but a longer wait for the same answer, and the useful thing
# to do with a budget is to spend it on attempts. Five seconds is twenty times a working
# connection, and retrying is what covers a dependency that is briefly out of reach.
SERVER_SELECTION_TIMEOUT_MS = 5_000

# `connectTimeoutMS` is deliberately NOT set, and this is the correction of a mistake.
#
# It was lowered to five seconds alongside the number above, on the same reasoning. The
# reasoning did not transfer. Server selection is what the retry loop below drives, so
# shortening it turns one long wait into several attempts and is the whole point. Opening a
# socket is not retried by anything here: it is done by the connection pool, on demand, for
# every operation that needs a connection - and the startup sequence needs several, in
# parallel, immediately after the ping succeeds.
#
# What that cost, observed on a deployment forced to start during a slow-egress window: the
# ping was retried and answered on the third attempt, and five seconds later index creation
# opened a new pool connection into the same unsettled network and failed, because it had been
# given a quarter of the headroom it used to have.
#
# There is a second effect, less obvious and not fixed by this line. Retrying makes the ping
# succeed sooner - the moment the network is reachable at all, rather than once it has settled
# - so the operations after it now run earlier, in worse conditions, than they used to. Giving
# the socket its full default again is necessary for that and may not be sufficient; the
# startup sequence as a whole is still unretried. See S11.24.

# Far enough apart that a cold start does not spend its budget on a dependency that needs a
# moment, close enough that it is not what the user is waiting for.
SECONDS_BETWEEN_ATTEMPTS = 2.0

# Overridden by BACKEND_DATABASE_STARTUP_BUDGET_SECONDS, which the deployment sets from the
# same place it sets the startup probe, so the two cannot drift apart. The default is for
# running outside a deployment, where there is no probe to be answerable to.
DEFAULT_STARTUP_BUDGET_SECONDS = 150.0
STARTUP_BUDGET_VARIABLE = "BACKEND_DATABASE_STARTUP_BUDGET_SECONDS"


class DatabaseRefusedPing(Exception):
    """The server was reached and answered the ping with something other than ``ok: 1``."""


def redact_mongodb_uri(uri: str) -> str:
    """
    A connection string reduced to user, host and database, safe to write to a log.

    Every message in this module reaches Cloud Logging, and from there a pasted bug
    report, so none of them may carry the password.
    """
    if not uri:
        return "<no connection string>"
    try:
        parts = urlsplit(uri)
    except ValueError:
        return "<unparseable connection string>"
    if not parts.hostname:
        return "<connection string>"
    user = f"{parts.username}:***@" if parts.username else ""
    netloc = f"{user}{parts.hostname}" + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def scrub_mongodb_credentials(message: str, uri: str = "") -> str:
    """
    Remove any password that a driver message carries.

    The driver quotes the whole connection string back in several of its errors — a
    ``ConfigurationError`` on an unresolvable host does it verbatim — so the text cannot
    be logged as it arrives.
    """
    if uri:
        message = message.replace(uri, redact_mongodb_uri(uri))
    return re.sub(r"://([^:/@\s]+):[^@/\s]+@", r"://\1:***@", message)


def open_mongo_client(mongodb_uri: str, **options) -> AsyncIOMotorClient:
    """
    Build a client, turning a connection string the driver will not take into a sentence.

    A ``mongodb+srv://`` host that does not resolve fails here, in the constructor, before
    there is anything to ping: the driver looks the SRV record up while parsing the URI.
    That surfaced as a bare ``ConfigurationError`` traceback out of a dependency function,
    with nothing to say which of six connection strings produced it - and for a malformed
    URI the driver quotes the string back, password included.

    :raises RuntimeError: naming the redacted connection string and the driver's reason
    """
    defaults = {
        # Only server selection is shortened; see the constant's own note for why
        # connectTimeoutMS is not, and what lowering it cost.
        "serverSelectionTimeoutMS": SERVER_SELECTION_TIMEOUT_MS,
        # socketTimeoutMS is deliberately left at the driver's default of no limit. It governs
        # an operation that is already running on a connection that already works, and this
        # application runs vector searches that legitimately take longer than any number that
        # would be right for reaching a server in the first place.
    }
    try:
        return AsyncIOMotorClient(mongodb_uri, **{**defaults, **options})
    except Exception as e:  # noqa: BLE001 - re-raised, with something to act on
        raise RuntimeError(
            f"The connection string {redact_mongodb_uri(mongodb_uri)} cannot be used: "
            f"{scrub_mongodb_credentials(f'{type(e).__name__}: {e}', mongodb_uri)}") from e


async def get_database_connection_info(database: AsyncIOMotorDatabase) -> str:
    """
    Retrieves connection information for a MongoDB database, formatted for logging.

    :param database: The MongoDB database object from AsyncIOMotorClient
    :return: A single-line string describing the database connection details
    """
    client = database.client
    db_name = database.name
    # Get the primary address (host and port)
    try:
        # Ensure the client is connected, before trying to get the client.address, otherwise it might be None
        si = await client.server_info()
        host, port = client.address
        primary_info = f"{host}:{port} version:{si.get('version', 'Unknown version')}"
    except Exception as e:  # noqa
        # Say which way it failed. "Unknown primary node" on its own reads as a cosmetic
        # gap in the log line rather than as the connection being unusable.
        primary_info = f"unreachable ({scrub_mongodb_credentials(f'{type(e).__name__}: {e}')})"

    # Get all connected nodes
    connected_nodes = client.nodes
    connected_nodes_info = ", ".join([f"{node[0]}:{node[1]}" for node in connected_nodes]) or "None"  # type: ignore

    # Format the output for logging
    connection_info = (
        f"Database: {db_name}, Primary: {primary_info}, Nodes: {connected_nodes_info}"
    )

    return connection_info


async def mongo_ping_failure(client: AsyncIOMotorClient) -> Optional[BaseException]:
    """
    None if MongoDB answers a ping, otherwise what went wrong, unflattened.

    The exception itself rather than a description of it, because the caller has to decide
    whether trying again could change the answer, and the driver's class is what says so.
    """
    try:
        result = await client.admin.command("ping")
    except Exception as e:  # noqa: BLE001 - every failure is a diagnosis, not a crash
        return e
    if math.isclose(result.get("ok", 0.0), 1.0):
        return None
    return DatabaseRefusedPing(f"the server answered the ping with {result!r}")


def describe_ping_failure(failure: BaseException, mongodb_uri: str = "") -> str:
    """The driver's own account of a failure, with any password taken out of it."""
    if isinstance(failure, DatabaseRefusedPing):
        return str(failure)
    return scrub_mongodb_credentials(f"{type(failure).__name__}: {failure}", mongodb_uri)


async def mongo_health_error(client: AsyncIOMotorClient) -> Optional[str]:
    """
    None if MongoDB answers a ping, otherwise the driver's own account of why it did not.

    The distinction the caller needs is between a wrong password, an unresolvable host,
    a TLS failure and an IP that the cluster's access list does not admit. The driver
    names all four; only a boolean return throws that away.

    :param client: The MongoDB client to check
    :return: None when healthy, else a scrubbed one-line description of the failure
    """
    failure = await mongo_ping_failure(client)
    return None if failure is None else describe_ping_failure(failure)


def is_transient_database_failure(failure: BaseException) -> bool:
    """
    Whether asking again could change the answer.

    ``ConnectionFailure`` and everything under it - server selection timing out, a node lost,
    a socket giving up - mean the driver could not reach a usable server. On a cold start that
    is routinely temporary, and measurably so: three such failures in this project's logs each
    cleared within a minute, on the same image, the same credentials and the same access list
    as the attempt that had just failed.

    Everything else is the deployment being wrong rather than unlucky. A wrong password and a
    user without rights on the database arrive as ``OperationFailure``; a connection string
    the driver cannot parse never reaches a ping at all, because ``open_mongo_client`` raises
    while building the client. No amount of waiting changes any of those, so the process says
    so at once instead of spending a startup budget rediscovering it.
    """
    return isinstance(failure, ConnectionFailure)


def database_startup_budget_seconds() -> float:
    """
    How long the first connection to a database may go on being retried.

    Set by the deployment from the same place it sets the Cloud Run startup probe, so that the
    time the application gives itself and the time the platform gives the application cannot
    drift apart. Read here rather than passed down from the top so that the number appears in
    the same file as the retry that spends it.
    """
    raw = os.getenv(STARTUP_BUDGET_VARIABLE)
    if raw is None:
        return DEFAULT_STARTUP_BUDGET_SECONDS
    try:
        budget = float(raw)
    except ValueError:
        budget = -1.0
    if budget < 0:
        logging.getLogger(__name__).warning(
            "%s is %r, which is not a number of seconds; using %.0fs.",
            STARTUP_BUDGET_VARIABLE, raw, DEFAULT_STARTUP_BUDGET_SECONDS)
        return DEFAULT_STARTUP_BUDGET_SECONDS
    return budget


async def require_healthy_database(database: AsyncIOMotorDatabase, *, label: str,
                                   mongodb_uri: str, logger: logging.Logger,
                                   budget_seconds: float = 0.0) -> None:
    """
    Raise unless the database answers a ping, naming which one and why it did not.

    Called before the "connected" log line rather than after it: a failure used to be
    announced as a successful connection followed by a health check that said only
    ``MongoDB health check failed for <X> database``. A bad password, an unresolvable
    host, a TLS error and an IP the cluster will not admit all produced that same
    sentence, so the first move was always to guess.

    ``budget_seconds`` is how long a failure that could clear on its own is retried for. The
    default of zero is one attempt, which is what a caller wants once the application is
    serving: a request should not sit behind a minute of retries. Startup passes a real budget,
    because the alternative there is not failing faster, it is the container exiting and the
    platform starting another one - the same retry, costing the user an instance and a minute
    instead of a second and nothing.

    A failure that waiting cannot fix is raised at once whatever the budget says.

    :raises RuntimeError: with the database, the redacted connection string and the cause
    """
    deadline = time.monotonic() + budget_seconds
    attempt = 0

    while True:
        attempt += 1
        failure = await mongo_ping_failure(database.client)
        if failure is None:
            if attempt > 1:
                logger.info("The %s database answered on attempt %d.", label, attempt)
            return

        message = (f"The {label} database '{database.name}' at {redact_mongodb_uri(mongodb_uri)} "
                   f"did not answer a ping: {describe_ping_failure(failure, mongodb_uri)}")
        remaining = deadline - time.monotonic()

        if not is_transient_database_failure(failure) or remaining < SECONDS_BETWEEN_ATTEMPTS:
            if attempt > 1:
                message = (f"{message} - given up on after {attempt} attempts over "
                           f"{budget_seconds:.0f}s")
            logger.warning(message)
            raise RuntimeError(message)

        logger.warning("%s - trying again in %.0fs, %.0fs of the startup budget left.",
                       message, SECONDS_BETWEEN_ATTEMPTS, remaining)
        await asyncio.sleep(SECONDS_BETWEEN_ATTEMPTS)


async def initialize_mongo_db_indexes(database: AsyncIOMotorDatabase, collection_name: str, indexes: list, logger: logging.Logger):
    """
    Initialize MongoDB indexes for a collection.
    
    :param database: The MongoDB database
    :param collection_name: The name of the collection to create indexes for
    :param indexes: List of index specifications
    :param logger: Logger instance for logging
    """
    try:
        logger.info(f"Initializing indexes for collection: {collection_name}")
        
        collection = database.get_collection(collection_name)
        for index_spec in indexes:
            await collection.create_index(index_spec["fields"], **index_spec.get("options", {}))
            
        logger.info(f"Finished creating indexes for collection: {collection_name}")
    except Exception as e:
        logger.exception(f"Error creating indexes for collection {collection_name}: {e}")
        raise e
