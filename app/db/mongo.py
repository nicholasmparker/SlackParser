"""MongoDB database connection module."""

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
import logging
from typing import Any, Tuple
import os

# Get environment variables
MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
MONGO_DB = os.getenv("MONGO_DB", "slack_data")

# Set up logging
logger = logging.getLogger(__name__)

# Global clients
async_client = None
sync_client = None

def get_db() -> Any:
    """Get the async MongoDB database instance."""
    global async_client
    if async_client is None:
        logger.warning("Async MongoDB client not initialized, initializing now")
        async_client = AsyncIOMotorClient(MONGO_URL)
    return async_client[MONGO_DB]

def get_sync_db() -> Any:
    """Get the sync MongoDB database instance."""
    global sync_client
    if sync_client is None:
        logger.warning("Sync MongoDB client not initialized, initializing now")
        sync_client = MongoClient(MONGO_URL)
    return sync_client[MONGO_DB]

async def connect_to_mongo() -> Tuple[Any, Any]:
    """Connect to MongoDB."""
    global async_client, sync_client
    
    # Initialize MongoDB clients
    async_client = AsyncIOMotorClient(MONGO_URL)
    sync_client = MongoClient(MONGO_URL)
    
    logger.info(f"Connected to MongoDB at {MONGO_URL}")
    
    # Return the database instances
    return get_db(), get_sync_db()

async def close_mongo_connection() -> None:
    """Close MongoDB connection."""
    global async_client, sync_client
    
    if async_client:
        async_client.close()
        logger.info("Closed async MongoDB connection")
    
    if sync_client:
        sync_client.close()
        logger.info("Closed sync MongoDB connection")

async def setup_indexes(db: Any) -> None:
    """Create necessary database indexes."""
    try:
        # Create text index on messages collection
        await db.messages.create_index([("text", "text")])
        # Create index on conversation_id for faster lookups
        await db.messages.create_index("conversation_id")
        # Create index on ts for sorting
        await db.messages.create_index("ts")
        # Create index on username
        await db.messages.create_index("username")
        
        # Create indexes for conversations collection
        await db.conversations.create_index("channel_id", unique=True)
        await db.conversations.create_index("name")
        await db.conversations.create_index("type")
        
        logger.info("Created database indexes")
    except Exception as e:
        logger.error(f"Error creating indexes: {e}")
        raise e
