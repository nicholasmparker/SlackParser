from motor.motor_asyncio import AsyncIOMotorClient
import asyncio

async def check():
    client = AsyncIOMotorClient('mongodb://mongodb:27017')
    doc = await client.slack_db.uploads.find_one(sort=[('_id', -1)])
    print(doc)

if __name__ == "__main__":
    asyncio.run(check())
