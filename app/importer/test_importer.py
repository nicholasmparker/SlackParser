"""
Test the importer module against real Slack export data.
"""

import os
import pytest
from datetime import datetime
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

from app.importer.importer import process_file, import_slack_export

# MongoDB setup - use Docker container
MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
MONGO_DB = os.getenv("MONGO_DB", "slack_data")
db = AsyncIOMotorClient(MONGO_URL)[MONGO_DB]

# Data directory in Docker
DATA_DIR = os.getenv("DATA_DIR", "/data")

@pytest.mark.asyncio
async def test_process_real_channel():
    """Test processing a real channel file from the extracts"""
    # Find a real channel file
    extract_path = Path(DATA_DIR) / "extracts"
    channel_files = list(extract_path.glob("*/slack-export-*/channels/*/*.txt"))
    assert channel_files, "No channel files found in extracts"
    
    # Process the first channel file
    channel_file = channel_files[0]
    print(f"\nTesting with channel file: {channel_file}")
    
    channel, messages = await process_file(db, channel_file, ObjectId())
    
    # Verify channel metadata
    assert channel.id.startswith("C"), "Channel ID should start with C"
    assert channel.name, "Channel should have a name"
    assert channel.created, "Channel should have creation date"
    
    # Verify messages
    assert messages, "Should have parsed some messages"
    for msg in messages:
        assert msg.channel_id == channel.id, "Message should reference channel"
        assert msg.username, "Message should have username"
        assert msg.text, "Message should have text"
        assert msg.ts, "Message should have timestamp"
        assert msg.type in ["message", "system", "archive", "file"], "Invalid message type"
        
        if msg.type == "system":
            assert msg.system_action, "System message should have action"
        elif msg.type == "file":
            assert msg.file_id, "File message should have file ID"
            
    print(f"Successfully processed {len(messages)} messages from channel {channel.name}")

@pytest.mark.asyncio
async def test_process_real_dm():
    """Test processing a real DM file from the extracts"""
    # Find a real DM file
    extract_path = Path(DATA_DIR) / "extracts"
    dm_files = list(extract_path.glob("*/slack-export-*/dms/*/*.txt"))
    assert dm_files, "No DM files found in extracts"
    
    # Process the first DM file
    dm_file = dm_files[0]
    print(f"\nTesting with DM file: {dm_file}")
    
    channel, messages = await process_file(db, dm_file, ObjectId())
    
    # Verify DM metadata
    assert channel.id.startswith("D"), "DM ID should start with D"
    assert channel.name.startswith("DM:"), "DM name should start with DM:"
    assert channel.created, "DM should have creation date"
    assert channel.dm_users, "Should have DM users list"
    assert len(channel.dm_users) >= 2, "Should have at least 2 users"
    
    # Verify messages
    assert messages, "Should have parsed some messages"
    for msg in messages:
        assert msg.channel_id == channel.id, "Message should reference DM"
        assert msg.username, "Message should have username"
        assert msg.text, "Message should have text"
        assert msg.ts, "Message should have timestamp"
        assert msg.type in ["message", "system", "archive", "file"], "Invalid message type"
        
    print(f"Successfully processed {len(messages)} messages from DM {channel.name}")

@pytest.mark.asyncio
async def test_full_import():
    """Test importing a complete Slack export"""
    # Find the most recent extract
    extract_path = Path(DATA_DIR) / "extracts"
    exports = list(extract_path.glob("*/slack-export-*"))
    assert exports, "No exports found in extracts"
    export_path = exports[0]
    print(f"\nTesting full import with: {export_path}")
    
    # Clean test database
    await db.channels.delete_many({})
    await db.messages.delete_many({})
    await db.users.delete_many({})
    await db.uploads.delete_many({})
    await db.failed_imports.delete_many({})
    
    # Create test upload
    upload_id = ObjectId()
    await db.uploads.insert_one({
        "_id": upload_id,
        "filename": "test_export.zip",
        "status": "EXTRACTING",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "size": 0,
        "uploaded_size": 0,
        "progress": "",
        "progress_percent": 0
    })
    
    # Run import
    await import_slack_export(db, export_path, upload_id)
    
    # Verify results
    channels = await db.channels.count_documents({})
    messages = await db.messages.count_documents({})
    users = await db.users.count_documents({})
    failures = await db.failed_imports.count_documents({"upload_id": upload_id})
    
    print(f"\nImport results:")
    print(f"- Channels/DMs: {channels}")
    print(f"- Messages: {messages}")
    print(f"- Users: {users}")
    print(f"- Failed imports: {failures}")
    
    # Verify upload status
    upload = await db.uploads.find_one({"_id": upload_id})
    assert upload["status"] == "COMPLETED", f"Import failed: {upload.get('error')}"
    assert upload["progress_percent"] == 100, "Import did not complete"
