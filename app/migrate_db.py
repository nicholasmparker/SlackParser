from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get environment variables
MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
MONGO_DB = os.getenv("MONGO_DB", "slack_data")

async def migrate_database():
    """Migrate data from slack_db to slack_data"""
    try:
        # Connect to MongoDB
        client = AsyncIOMotorClient(MONGO_URL)
        source_db = client.slack_db
        target_db = client[MONGO_DB]
        
        # Collections to migrate
        collections = ["messages", "conversations", "uploads", "import_status", "files"]
        
        for collection in collections:
            # Count documents in source
            count = await source_db[collection].count_documents({})
            logger.info(f"Found {count} documents in slack_db.{collection}")
            
            if count > 0:
                # Get all documents
                docs = await source_db[collection].find({}).to_list(length=None)
                
                # Insert into target
                if docs:
                    await target_db[collection].insert_many(docs)
                    logger.info(f"Migrated {len(docs)} documents to {MONGO_DB}.{collection}")
            
        logger.info("Migration complete!")
        
    except Exception as e:
        logger.error(f"Error during migration: {str(e)}")

if __name__ == "__main__":
    asyncio.run(migrate_database())
