import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
MONGO_DB = os.getenv("MONGO_DB", "slack_data")

async def test_mongo():
    """Test MongoDB connection and query messages"""
    try:
        # Connect to MongoDB
        logger.info("Connecting to MongoDB...")
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[MONGO_DB]
        
        # Test connection
        await client.admin.command('ping')
        logger.info("Successfully connected to MongoDB")
        
        # Count messages
        count = await db.messages.count_documents({})
        logger.info(f"Found {count} messages")
        
        # Get a sample message
        message = await db.messages.find_one({})
        if message:
            logger.info("Sample message:")
            logger.info(message)
        else:
            logger.info("No messages found")
            
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(test_mongo())
