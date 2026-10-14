import asyncio
import logging

from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from common_libs.database.get_mongo_db_connection import get_mongo_db_connection
from common_libs.database.utils import database_startup_budget_seconds, \
    get_database_connection_info, require_healthy_database
from features.skills_ranking.config import get_skills_ranking_config

_registration_data_db_singleton: AsyncIOMotorDatabase | None = None
_registration_data_db_lock = asyncio.Lock()


_logger = logging.getLogger(__name__)

async def get_registration_data_db(
        mongo_db_uri: str = Depends(lambda: get_skills_ranking_config().registration_data_mongodb_uri),
        database_name: str = Depends(
            lambda: get_skills_ranking_config().registration_data_database_name)) -> AsyncIOMotorDatabase:
    global _registration_data_db_singleton

    # initial check to avoid the lock if the singleton instance is already created (lock is expensive)
    if _registration_data_db_singleton is None:

        # before modifying the singleton instance, acquire the lock
        async with _registration_data_db_lock:
            # double check after acquiring the lock
            if _registration_data_db_singleton is None:
                _logger.info("Connecting to Registration Data MongoDB")

                # Create the database instance
                database = get_mongo_db_connection(mongo_db_uri, database_name)

                await require_healthy_database(database, label="Registration Data",
                                               mongodb_uri=mongo_db_uri, logger=_logger,
                                               budget_seconds=database_startup_budget_seconds())

                _logger.info("Connected to Registration Data database: %s",
                             await get_database_connection_info(database))
                _registration_data_db_singleton = database

    return _registration_data_db_singleton
