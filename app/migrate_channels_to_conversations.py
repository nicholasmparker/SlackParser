#!/usr/bin/env python3
"""
Migration script to copy data from channels collection to conversations collection.
This is needed because the import process stores data in the channels collection,
but the frontend looks for data in the conversations collection.
"""

import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from datetime import datetime

# MongoDB connection settings
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "slack_data")


async def migrate_channels_to_conversations():
    """Migrate data from channels collection to conversations collection."""
    # Connect to MongoDB
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[MONGO_DB]

    print(f"Connected to MongoDB: {MONGO_URL}")
    print(f"Using database: {MONGO_DB}")

    # Count channels
    channel_count = await db.channels.count_documents({})
    print(f"Found {channel_count} channels to migrate")

    # Clear existing conversations
    await db.conversations.delete_many({})
    print("Cleared existing conversations collection")

    # Migrate channels to conversations
    channels = await db.channels.find({}).to_list(length=None)

    if not channels:
        print("No channels found to migrate")
        return

    # Prepare conversations for bulk insert
    conversations = []
    for channel in channels:
        # Convert channel to conversation format
        conversation = {
            "_id": ObjectId(),  # Generate new ID
            "name": channel["name"],
            "type": "dm" if channel.get("is_dm", False) else "channel",
            "channel_id": channel["id"],  # Keep original channel ID
            "created_at": channel.get("created", datetime.utcnow()),
            "updated_at": datetime.utcnow(),
            "topic": channel.get("topic"),
            "purpose": channel.get("purpose"),
            "is_archived": channel.get("is_archived", False),
            "dm_users": channel.get("dm_users", []) if channel.get("is_dm", False) else []
        }
        conversations.append(conversation)

    # Insert conversations
    if conversations:
        result = await db.conversations.insert_many(conversations)
        print(f"Migrated {len(result.inserted_ids)} channels to conversations")

    # Update message references
    for channel in channels:
        # Find messages for this channel
        update_result = await db.messages.update_many(
            {"channel_id": channel["id"]},
            {"$set": {"conversation_id": channel["id"]}}
        )
        print(f"Updated {update_result.modified_count} messages for channel {channel['name']}")

    print("Migration complete!")


if __name__ == "__main__":
    asyncio.run(migrate_channels_to_conversations())
