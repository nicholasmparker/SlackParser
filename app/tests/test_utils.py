"""Utility functions for testing."""

import os
import json
import pytest
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from bson import ObjectId

# Constants for test data
TEST_CHANNEL_ID = "C12345"
TEST_DM_ID = "D12345"
TEST_USER_ID = "U12345"
TEST_TIMESTAMP = datetime.utcnow()

def async_test(coro):
    """Decorator for running async tests outside of pytest-asyncio."""
    def wrapper(*args, **kwargs):
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro(*args, **kwargs))
    return wrapper

def create_test_message(
    text: str,
    username: str = "testuser",
    conversation_id: str = TEST_CHANNEL_ID,
    ts: Optional[Union[float, datetime]] = None,
    message_type: str = "message",
    **kwargs
) -> Dict[str, Any]:
    """Create a test message document for MongoDB."""
    if ts is None:
        ts = TEST_TIMESTAMP

    # Convert datetime to timestamp if needed
    if isinstance(ts, datetime):
        ts = ts.timestamp()

    message = {
        "_id": ObjectId(),
        "text": text,
        "username": username,
        "conversation_id": conversation_id,
        "ts": ts,
        "type": message_type,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    # Add any additional fields
    message.update(kwargs)

    return message

def create_test_conversation(
    name: str,
    channel_id: str = TEST_CHANNEL_ID,
    conversation_type: str = "channel",
    topic: str = "Test topic",
    purpose: str = "Test purpose",
    is_dm: bool = False,
    dm_users: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Create a test conversation document for MongoDB."""
    conversation = {
        "_id": ObjectId(),
        "name": name,
        "channel_id": channel_id,
        "type": conversation_type,
        "topic": topic,
        "purpose": purpose,
        "is_dm": is_dm,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    if is_dm and dm_users:
        conversation["dm_users"] = dm_users

    return conversation

def create_test_upload(
    filename: str = "test_export.zip",
    status: str = "UPLOADED",
    file_path: Optional[str] = None,
    extract_path: Optional[str] = None,
    size: int = 1024
) -> Dict[str, Any]:
    """Create a test upload document for MongoDB."""
    upload_id = ObjectId()

    if file_path is None:
        file_path = f"/tmp/{upload_id}_{filename}"

    if extract_path is None and status in ["EXTRACTED", "IMPORTED"]:
        extract_path = f"/tmp/extracts/{upload_id}"

    upload = {
        "_id": upload_id,
        "filename": filename,
        "file_path": file_path,
        "status": status,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "size": size,
        "uploaded_size": size,
        "progress_percent": 100 if status in ["EXTRACTED", "IMPORTED"] else 0
    }

    if extract_path:
        upload["extract_path"] = extract_path

    return upload

async def populate_test_db(db, num_conversations=2, messages_per_conversation=5):
    """Populate the test database with sample data."""
    # Create conversations
    conversations = []
    for i in range(num_conversations):
        is_dm = i % 2 == 1  # Every other conversation is a DM

        if is_dm:
            conv = create_test_conversation(
                name=f"DM: user1-user{i+1}",
                channel_id=f"D{i+1}",
                conversation_type="dm",
                is_dm=True,
                dm_users=["user1", f"user{i+1}"]
            )
        else:
            conv = create_test_conversation(
                name=f"channel-{i+1}",
                channel_id=f"C{i+1}",
                conversation_type="channel"
            )

        conversations.append(conv)

    # Insert conversations
    if conversations:
        await db.conversations.insert_many(conversations)

    # Create messages for each conversation
    all_messages = []
    for conv in conversations:
        for j in range(messages_per_conversation):
            msg = create_test_message(
                text=f"Test message {j+1} in {conv['name']}",
                username="user1" if j % 2 == 0 else f"user{j+1}",
                conversation_id=conv["channel_id"],
                ts=datetime.utcnow().timestamp() + j
            )
            all_messages.append(msg)

    # Insert messages
    if all_messages:
        await db.messages.insert_many(all_messages)

    return {
        "conversations": conversations,
        "messages": all_messages
    }
