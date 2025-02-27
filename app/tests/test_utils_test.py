"""Tests for the test utility functions."""

import pytest
import asyncio
from datetime import datetime
from bson import ObjectId

from app.tests.test_utils import (
    create_test_message,
    create_test_conversation,
    create_test_upload,
    populate_test_db,
    async_test
)

@pytest.mark.unit
def test_create_test_message():
    """Test creating a test message."""
    # Test with minimal parameters
    message = create_test_message("Hello world")
    assert message["text"] == "Hello world"
    assert message["username"] == "testuser"
    assert isinstance(message["_id"], ObjectId)
    assert isinstance(message["ts"], float)

    # Test with custom parameters
    custom_ts = datetime(2023, 1, 1, 12, 0, 0)
    message = create_test_message(
        text="Custom message",
        username="customuser",
        conversation_id="C67890",
        ts=custom_ts,
        message_type="file",
        file_id="F12345"
    )

    assert message["text"] == "Custom message"
    assert message["username"] == "customuser"
    assert message["conversation_id"] == "C67890"
    assert message["ts"] == custom_ts.timestamp()
    assert message["type"] == "file"
    assert message["file_id"] == "F12345"

@pytest.mark.unit
def test_create_test_conversation():
    """Test creating a test conversation."""
    # Test channel
    channel = create_test_conversation("general")
    assert channel["name"] == "general"
    assert channel["type"] == "channel"
    assert not channel["is_dm"]

    # Test DM
    dm = create_test_conversation(
        name="DM: user1-user2",
        channel_id="D12345",
        conversation_type="dm",
        is_dm=True,
        dm_users=["user1", "user2"]
    )

    assert dm["name"] == "DM: user1-user2"
    assert dm["channel_id"] == "D12345"
    assert dm["type"] == "dm"
    assert dm["is_dm"]
    assert dm["dm_users"] == ["user1", "user2"]

@pytest.mark.unit
def test_create_test_upload():
    """Test creating a test upload."""
    # Test with minimal parameters
    upload = create_test_upload()
    assert upload["filename"] == "test_export.zip"
    assert upload["status"] == "UPLOADED"
    assert upload["size"] == 1024
    assert "extract_path" not in upload

    # Test with extracted status
    upload = create_test_upload(status="EXTRACTED")
    assert upload["status"] == "EXTRACTED"
    assert "extract_path" in upload
    assert upload["progress_percent"] == 100

@pytest.mark.asyncio
@pytest.mark.integration
async def test_populate_test_db(test_db):
    """Test populating the test database."""
    # Populate the database
    result = await populate_test_db(test_db, num_conversations=3, messages_per_conversation=2)

    # Check conversations
    assert len(result["conversations"]) == 3
    db_conversations = await test_db.conversations.find().to_list(length=10)
    assert len(db_conversations) == 3

    # Check messages
    assert len(result["messages"]) == 6  # 3 conversations * 2 messages
    db_messages = await test_db.messages.find().to_list(length=10)
    assert len(db_messages) == 6

    # Check conversation types
    channel_count = 0
    dm_count = 0
    for conv in db_conversations:
        if conv["is_dm"]:
            dm_count += 1
        else:
            channel_count += 1

    assert channel_count == 2  # Every other conversation is a channel
    assert dm_count == 1  # Every other conversation is a DM

@pytest.mark.unit
def test_async_test():
    """Test the async_test decorator."""

    @async_test
    async def sample_async_function():
        await asyncio.sleep(0.01)
        return 42

    # The decorator should allow us to call the async function synchronously
    result = sample_async_function()
    assert result == 42
