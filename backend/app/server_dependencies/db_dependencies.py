import asyncio
import logging
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from common_libs.database.utils import (database_startup_budget_seconds,
                                        get_database_connection_info, open_mongo_client,
                                        require_healthy_database)
from common_libs.environment_settings.mongo_db_settings import MongoDbSettings
from app.app_config import get_application_config
from .database_collections import Collections


def _get_or_create_client(mongodb_uri: str, clients: dict) -> AsyncIOMotorClient:
    """
    Returns an existing AsyncIOMotorClient for the given URI, or creates one.
    Sharing a client across databases on the same URI reuses the connection pool,
    reducing the total number of connections opened against the MongoDB cluster.
    """
    if mongodb_uri not in clients:
        clients[mongodb_uri] = open_mongo_client(
            mongodb_uri,
            tlsAllowInvalidCertificates=True
        )
    return clients[mongodb_uri]


def _get_application_db(mongodb_uri: str, db_name: str, clients: dict) -> AsyncIOMotorDatabase:
    """
    Decouples the database creation from the database provider.
    This allows to mock the database creation in tests, instead of mocking the database provider.
    """
    return _get_or_create_client(mongodb_uri, clients).get_database(db_name)


def _get_userdata_db(userdata_mongodb_uri: str, userdata_db_name: str, clients: dict) -> AsyncIOMotorDatabase:
    """
    Decouples the database creation from the database provider.
    This allows to mock the database creation in tests, instead of mocking the database provider.
    """
    return _get_or_create_client(userdata_mongodb_uri, clients).get_database(userdata_db_name)


def _get_taxonomy_db(mongodb_uri: str, db_name: str, clients: dict) -> AsyncIOMotorDatabase:
    """
    Decouples the database creation from the database provider.
    This allows to mock the database creation in tests, instead of mocking the database provider.
    """
    return _get_or_create_client(mongodb_uri, clients).get_database(db_name)


def _get_career_explorer_db(mongodb_uri: str, db_name: str, clients: dict) -> AsyncIOMotorDatabase:
    return _get_or_create_client(mongodb_uri, clients).get_database(db_name)


def _get_metrics_db(mongodb_uri: str, db_name: str, clients: dict) -> AsyncIOMotorDatabase:
    """
    Decouples the database creation from the database provider.
    This allows to mock the database creation in tests, instead of mocking the database provider.
    """
    return _get_or_create_client(mongodb_uri, clients).get_database(db_name)


def _get_jobs_db(mongodb_uri: str, db_name: str, clients: dict) -> AsyncIOMotorDatabase:
    """
    Decouples the Zambia jobs database creation from the provider.
    """
    return _get_or_create_client(mongodb_uri, clients).get_database(db_name)


class CompassDBProvider:
    """
    Provides the taxonomy and application database instances.
    """
    _application_mongo_db: Optional[AsyncIOMotorDatabase] = None
    _taxonomy_mongo_db: Optional[AsyncIOMotorDatabase] = None
    _userdata_mongo_db: Optional[AsyncIOMotorDatabase] = None
    _metrics_mongo_db: Optional[AsyncIOMotorDatabase] = None
    _career_explorer_mongo_db: Optional[AsyncIOMotorDatabase] = None
    _jobs_mongo_db: Optional[AsyncIOMotorDatabase] = None
    # Shared clients keyed by URI — databases on the same URI reuse one connection pool
    _clients: dict[str, AsyncIOMotorClient] = {}
    _lock = asyncio.Lock()
    _logger = logging.getLogger(__qualname__)

    @staticmethod
    def _get_settings() -> MongoDbSettings:
        # Deffer reading the settings until the first time they are needed
        # Otherwise, the settings will be read at import time which can cause issues with unset environment variables during testing
        return MongoDbSettings()

    @staticmethod
    async def initialize_userdata_mongo_db(userdata_db: AsyncIOMotorDatabase, logger: logging.Logger):
        """ Initialize the MongoDB database."""
        try:
            logger.info("Initializing indexes for the userdata database")
            # Create the sensitive personal data indexes
            await userdata_db.get_collection(Collections.SENSITIVE_PERSONAL_DATA).create_index([
                ("user_id", 1)
            ], unique=True)

            # Create the plain personal data indexes
            await userdata_db.get_collection(Collections.PLAIN_PERSONAL_DATA).create_index([
                ("user_id", 1)
            ], unique=True)

            # Create the indexes related to the user cv uploads (only if CV upload is enabled)
            app_config = get_application_config()
            if app_config.enable_cv_upload:
                # 2 User-CV-Upload documents cannot reference to the
                #   — same object path.
                #   — same Markdown object path.
                #
                # This will help us prevent deleting documents of others and rate limiting users.
                await userdata_db.get_collection(Collections.USER_CV_UPLOADS).create_index([
                    ("object_path", 1)
                ], unique=True)
                await userdata_db.get_collection(Collections.USER_CV_UPLOADS).create_index([
                    ("markdown_object_path", 1)
                ], unique=True)

                # Create a unique compound index on user_id and MD5 hash to prevent duplicate file uploads per user
                await userdata_db.get_collection(Collections.USER_CV_UPLOADS).create_index([
                    ("user_id", 1),
                    ("md5_hash", 1)
                ], unique=True)

                # Create a sortable index because we are searching user's CV uploads frequently, and we are filtering by
                #   user_id and upload_process_state. e.g.: finding successfully uploaded cvs.
                await userdata_db.get_collection(Collections.USER_CV_UPLOADS).create_index([
                    ("user_id", 1),
                    ("upload_process_state", 1)
                ])

                # Ensure fast lookups by upload_id (used by status and cancellation routes)
                await userdata_db.get_collection(Collections.USER_CV_UPLOADS).create_index([
                    ("upload_id", 1)
                ], unique=True)

                # Speed up rate-limit queries: count uploads in a time window per user
                await userdata_db.get_collection(Collections.USER_CV_UPLOADS).create_index([
                    ("user_id", 1),
                    ("created_at", 1)
                ])
                logger.info("CV upload indexes created")
            else:
                logger.info("CV upload indexes skipped (GLOBAL_ENABLE_CV_UPLOAD is not enabled)")

            logger.info("Finished creating indexes for the userdata database")
        except Exception as e:
            logger.exception(e)
            raise e

    @staticmethod
    async def initialize_application_mongo_db(application_db: AsyncIOMotorDatabase, logger: logging.Logger):
        """ Initialize the MongoDB database."""
        try:
            logger.info("Initializing indexes for the application database")
            # Create the user preferences indexes
            await application_db.get_collection(Collections.USER_PREFERENCES).create_index([
                ("user_id", 1)
            ], unique=True)

            # Create the user invitations indexes
            await application_db.get_collection(Collections.USER_INVITATIONS).create_index([
                ("invitation_code", 1)
            ], unique=True)

            # Create indexes for the application state elements
            await application_db.get_collection(Collections.AGENT_DIRECTOR_STATE).create_index([
                ("session_id", 1)
            ], unique=True)

            await application_db.get_collection(Collections.EXPLORE_EXPERIENCES_DIRECTOR_STATE).create_index([
                ("session_id", 1)
            ], unique=True)

            await application_db.get_collection(Collections.CONVERSATION_MEMORY_MANAGER_STATE).create_index([
                ("session_id", 1)
            ], unique=True)

            await application_db.get_collection(Collections.COLLECT_EXPERIENCE_STATE).create_index([
                ("session_id", 1)
            ], unique=True)

            await application_db.get_collection(Collections.SKILLS_EXPLORER_AGENT_STATE).create_index([
                ("session_id", 1)
            ], unique=True)

            # Create the user feedback indexes
            await application_db.get_collection(Collections.USER_FEEDBACK).create_index([
                ("user_id", 1), ("session_id", 1)
            ])

            await application_db.get_collection(Collections.USER_FEEDBACK).create_index([
                ("session_id", 1)
            ], unique=True)

            await application_db.get_collection(Collections.REACTIONS).create_index([
                ("session_id", 1),
                ("message_id", 1)
            ], unique=True)

            # Add unique index on message_id for reactions
            await application_db.get_collection(Collections.REACTIONS).create_index([
                ("message_id", 1)
            ], unique=True)

            # TODO: add additional indexes as needed
            await application_db.get_collection(Collections.JOBS).create_index([
                ("session_id", 1)
            ])

            # Create the job preferences indexes
            await application_db.get_collection(Collections.JOB_PREFERENCES).create_index([
                ("session_id", 1)
            ], unique=True)

            # Create the career path indexes
            await application_db.get_collection(Collections.CAREER_PATH).create_index([
                ("id", 1)
            ])

            await application_db.get_collection(Collections.USER_RECOMMENDATIONS).create_index([
                ("user_id", 1)
            ], unique=True)

            # Create the career readiness conversations indexes
            await application_db.get_collection(Collections.CAREER_READINESS_CONVERSATIONS).create_index([
                ("conversation_id", 1)
            ], unique=True)

            await application_db.get_collection(Collections.CAREER_READINESS_CONVERSATIONS).create_index([
                ("user_id", 1), ("module_id", 1)
            ], unique=True)

            # Create the institutions indexes
            # Note: keyword search uses an Atlas Search index ("institutions_search") which must
            # be created manually in the Atlas UI or via the Atlas Admin API — see repository.py
            # for the required index definition.
            await application_db.get_collection(Collections.INSTITUTIONS).create_index(
                [("reg_no", 1)], sparse=True
            )
            await application_db.get_collection(Collections.INSTITUTIONS).create_index(
                [("location.province", 1)]
            )

            # Admin registrations:
            # - unique partial index on email where status is pending or approved (allows
            #   rejected rows to be overwritten on resubmit while blocking duplicate active rows)
            # - status + submitted_at index for the dashboard list
            await application_db.get_collection(Collections.ADMIN_REGISTRATIONS).create_index(
                [("email", 1)],
                unique=True,
                partialFilterExpression={"status": {"$in": ["pending", "approved"]}},
                name="email_active_unique",
            )
            await application_db.get_collection(Collections.ADMIN_REGISTRATIONS).create_index(
                [("status", 1), ("submitted_at", -1)],
            )

            # Pilot whitelisting indexes
            await application_db.get_collection(Collections.PILOT_WHITELIST).create_index(
                [("institution_name", 1)], unique=True
            )
            await application_db.get_collection(Collections.USER_INSTITUTION_ASSIGNMENT).create_index(
                [("user_id", 1)], unique=True
            )

            logger.info("Finished creating indexes for the application database")
        except Exception as e:
            logger.exception(e)
            raise e

    @staticmethod
    async def initialize_career_explorer_mongo_db(career_explorer_db: AsyncIOMotorDatabase, logger: logging.Logger):
        try:
            logger.info("Initializing indexes for the Career Explorer database")
            await career_explorer_db.get_collection(Collections.CAREER_EXPLORER_CONVERSATIONS).create_index([
                ("user_id", 1)
            ], unique=True)
            logger.info("Finished creating indexes for the Career Explorer database")
        except Exception as e:
            logger.exception(e)
            raise e

    @staticmethod
    async def initialize_metrics_mongo_db(metrics_db: AsyncIOMotorDatabase, logger: logging.Logger):
        """ Initialize the MongoDB database."""
        try:
            logger.info("Initializing indexes for the metrics database")

            # This compound index covers 3 types of queries:
            # - queries that filter by event_type (for most events)
            # - queries that filter by event_type, anonymized_user_id, and anonymized_session_id (for upserting FeedbackProvided events)
            # - queries that filter by event_type, anonymized_user_id, anonymized_session_id and message_id (for upserting Reaction events)
            await metrics_db.get_collection(Collections.COMPASS_METRICS).create_index([
                ("event_type", 1),
                ("anonymized_user_id", 1),
                ("anonymized_session_id", 1),
                ("message_id", 1)
            ], sparse=True)

            logger.info("Finished creating indexes for the metrics database")
        except Exception as e:
            logger.exception(e)
            raise e

    @classmethod
    async def get_application_db(cls) -> AsyncIOMotorDatabase:
        if cls._application_mongo_db is None:  # Check if the database instance has been created
            async with cls._lock:  # Ensure that only one coroutine is creating and initializing the database instance
                if cls._application_mongo_db is None:  # Double-check after acquiring the lock
                    cls._logger.info("Connecting to Application MongoDB")
                    settings = cls._get_settings()
                    database = _get_application_db(settings.application_mongodb_uri,
                                                   settings.application_database_name,
                                                   cls._clients)
                    await require_healthy_database(database, label="Application",
                                                   mongodb_uri=settings.application_mongodb_uri,
                                                   logger=cls._logger,
                                                   budget_seconds=database_startup_budget_seconds())
                    cls._logger.info("Connected to Application MongoDB database: %s",
                                     await get_database_connection_info(database))
                    cls._application_mongo_db = database

        return cls._application_mongo_db

    @classmethod
    async def get_userdata_db(cls) -> AsyncIOMotorDatabase:
        """
        Get the userdata database instance.
        :return: AsyncIOMotorDatabase[userdata_db_name]
        """
        if cls._userdata_mongo_db is None:  # Check if the database instance has been created
            async with cls._lock:  # Ensure that only one coroutine is creating and initializing the database instance
                if cls._userdata_mongo_db is None:  # Double-check after acquiring the lock
                    cls._logger.info("Connecting to Userdata MongoDB")
                    settings = cls._get_settings()
                    database = _get_userdata_db(
                        settings.userdata_mongodb_uri,
                        settings.userdata_database_name,
                        cls._clients
                    )
                    await require_healthy_database(database, label="Userdata",
                                                   mongodb_uri=settings.userdata_mongodb_uri,
                                                   logger=cls._logger,
                                                   budget_seconds=database_startup_budget_seconds())
                    cls._logger.info("Connected to Userdata MongoDB database: %s",
                                     await get_database_connection_info(database))
                    cls._userdata_mongo_db = database
        return cls._userdata_mongo_db

    @classmethod
    async def get_taxonomy_db(cls) -> AsyncIOMotorDatabase:
        if cls._taxonomy_mongo_db is None:  # Check if the database instance has been created
            async with cls._lock:  # Ensure that only one coroutine is creating and initializing the database instance
                if cls._taxonomy_mongo_db is None:  # Double-check after acquiring the lock
                    cls._logger.info("Connecting to Taxonomy MongoDB")
                    settings = cls._get_settings()
                    database = _get_taxonomy_db(settings.taxonomy_mongodb_uri,
                                                settings.taxonomy_database_name,
                                                cls._clients)
                    await require_healthy_database(database, label="Taxonomy",
                                                   mongodb_uri=settings.taxonomy_mongodb_uri,
                                                   logger=cls._logger,
                                                   budget_seconds=database_startup_budget_seconds())
                    cls._logger.info("Connected to Taxonomy MongoDB database: %s",
                                     await get_database_connection_info(database))
                    cls._taxonomy_mongo_db = database
        return cls._taxonomy_mongo_db

    @classmethod
    async def get_career_explorer_db(cls) -> AsyncIOMotorDatabase:
        if cls._career_explorer_mongo_db is None:
            async with cls._lock:
                if cls._career_explorer_mongo_db is None:
                    cls._logger.info("Connecting to Career Explorer MongoDB")
                    settings = cls._get_settings()
                    database = _get_career_explorer_db(
                        settings.career_explorer_mongodb_uri,
                        settings.career_explorer_database_name,
                        cls._clients,
                    )
                    await require_healthy_database(database, label="Career Explorer",
                                                   mongodb_uri=settings.career_explorer_mongodb_uri,
                                                   logger=cls._logger,
                                                   budget_seconds=database_startup_budget_seconds())
                    cls._logger.info("Connected to Career Explorer MongoDB database: %s",
                                     await get_database_connection_info(database))
                    cls._career_explorer_mongo_db = database
        return cls._career_explorer_mongo_db

    @classmethod
    async def get_metrics_db(cls) -> AsyncIOMotorDatabase:
        if cls._metrics_mongo_db is None:  # Check if the database instance has been created
            async with cls._lock:  # Ensure that only one coroutine is creating and initializing the database instance
                if cls._metrics_mongo_db is None:  # Double-check after acquiring the lock
                    cls._logger.info("Connecting to Metrics MongoDB")
                    settings = cls._get_settings()
                    database = _get_metrics_db(settings.metrics_mongodb_uri,
                                               settings.metrics_database_name,
                                               cls._clients)
                    await require_healthy_database(database, label="Metrics",
                                                   mongodb_uri=settings.metrics_mongodb_uri,
                                                   logger=cls._logger,
                                                   budget_seconds=database_startup_budget_seconds())
                    cls._logger.info("Connected to Metrics MongoDB database: %s",
                                     await get_database_connection_info(database))
                    cls._metrics_mongo_db = database
        return cls._metrics_mongo_db

    @classmethod
    async def get_jobs_db(cls) -> AsyncIOMotorDatabase:
        if cls._jobs_mongo_db is None:
            async with cls._lock:
                if cls._jobs_mongo_db is None:
                    cls._logger.info("Connecting to Jobs MongoDB")
                    settings = cls._get_settings()
                    database = _get_jobs_db(
                        settings.jobs_mongodb_uri,
                        settings.jobs_database_name,
                        cls._clients
                    )
                    await require_healthy_database(database, label="Jobs",
                                                   mongodb_uri=settings.jobs_mongodb_uri,
                                                   logger=cls._logger,
                                                   budget_seconds=database_startup_budget_seconds())
                    cls._logger.info("Connected to Jobs MongoDB database: %s",
                                     await get_database_connection_info(database))
                    cls._jobs_mongo_db = database
        return cls._jobs_mongo_db

    @staticmethod
    def clear_cache():
        """
        Clear the cached database instances.

        This is useful for testing purposes to ensure that the database instances are re-created.
        """
        CompassDBProvider._application_mongo_db = None
        CompassDBProvider._taxonomy_mongo_db = None
        CompassDBProvider._userdata_mongo_db = None
        CompassDBProvider._metrics_mongo_db = None
        CompassDBProvider._career_explorer_mongo_db = None
        CompassDBProvider._jobs_mongo_db = None
        CompassDBProvider._clients = {}

        CompassDBProvider._logger.info("Cleared cached database instances")
