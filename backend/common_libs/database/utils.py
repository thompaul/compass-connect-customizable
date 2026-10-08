import logging
import math
import re
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase


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
    try:
        return AsyncIOMotorClient(mongodb_uri, **options)
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


async def mongo_health_error(client: AsyncIOMotorClient) -> Optional[str]:
    """
    None if MongoDB answers a ping, otherwise the driver's own account of why it did not.

    The distinction the caller needs is between a wrong password, an unresolvable host,
    a TLS failure and an IP that the cluster's access list does not admit. The driver
    names all four; only a boolean return throws that away.

    :param client: The MongoDB client to check
    :return: None when healthy, else a scrubbed one-line description of the failure
    """
    try:
        result = await client.admin.command("ping")
    except Exception as e:  # noqa: BLE001 - every failure is a diagnosis, not a crash
        return scrub_mongodb_credentials(f"{type(e).__name__}: {e}")
    if math.isclose(result.get("ok", 0.0), 1.0):
        return None
    return f"the server answered the ping with {result!r}"


async def require_healthy_database(database: AsyncIOMotorDatabase, *, label: str,
                                   mongodb_uri: str, logger: logging.Logger) -> None:
    """
    Raise unless the database answers a ping, naming which one and why it did not.

    Called before the "connected" log line rather than after it: a failure used to be
    announced as a successful connection followed by a health check that said only
    ``MongoDB health check failed for <X> database``. A bad password, an unresolvable
    host, a TLS error and an IP the cluster will not admit all produced that same
    sentence, so the first move was always to guess.

    :raises RuntimeError: with the database, the redacted connection string and the cause
    """
    failure = await mongo_health_error(database.client)
    if failure is None:
        return

    message = (f"The {label} database '{database.name}' at {redact_mongodb_uri(mongodb_uri)} "
               f"did not answer a ping: {scrub_mongodb_credentials(failure, mongodb_uri)}")
    logger.warning(message)
    raise RuntimeError(message)


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
