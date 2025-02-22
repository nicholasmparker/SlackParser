import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def test_mongo():
    try:
        # Connect to MongoDB
        logger.info("Connecting to MongoDB...")
        client = AsyncIOMotorClient(os.getenv("MONGODB_URL", "mongodb://localhost:27017"))
        db = client.slack_db
        
        # Count messages
        count = await db.messages.count_documents({})
        logger.info(f"Found {count} messages")
        
        # Get one message
        message = await db.messages.find_one({})
        if message:
            logger.info(f"Sample message: {message}")
        else:
            logger.info("No messages found")
            
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(test_mongo())
