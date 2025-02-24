from motor.motor_asyncio import AsyncIOMotorClient
import os
import asyncio

MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
MONGO_DB = os.getenv("MONGO_DB", "slack_data")

async def check():
    client = AsyncIOMotorClient(MONGO_URL)
    doc = await client[MONGO_DB].uploads.find_one(sort=[('_id', -1)])
    print(doc)

if __name__ == "__main__":
    asyncio.run(check())
