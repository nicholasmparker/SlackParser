"""Configuration for pytest."""

import os
import shutil
import pytest
import asyncio
from pathlib import Path
import zipfile
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock
from pymongo import MongoClient
from motor.motor_asyncio import AsyncIOMotorClient

from app.new_main import app
from app.services.main_service import MainService
from fastapi.testclient import TestClient

# Create a test client
@pytest.fixture(scope="session")
def client():
    """Create a FastAPI test client."""
    return TestClient(app)

@pytest.fixture(scope="session")
def data_dir():
    """Get the data directory path.

    In Docker, this will be /data
    For local testing, we'll use the same path to match Docker environment
    """
    data_dir = os.getenv("DATA_DIR", "/data")
    return data_dir

@pytest.fixture(scope="session")
def upload_dir(data_dir):
    """Get the upload directory path."""
    upload_dir = os.path.join(data_dir, "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir

@pytest.fixture(scope="session")
def extract_dir(data_dir):
    """Get the extract directory path."""
    extract_dir = os.path.join(data_dir, "extracts")
    os.makedirs(extract_dir, exist_ok=True)
    return extract_dir

# Use session scope to keep the event loop alive for all tests
@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for all tests."""
    # Get the current event loop policy
    policy = asyncio.get_event_loop_policy()

    # Create a new event loop
    loop = policy.new_event_loop()

    # Set it as the current event loop
    asyncio.set_event_loop(loop)
    yield loop  # This loop will be used for all tests
    # We don't close the loop to avoid "Event loop is closed" errors

@pytest.fixture(scope="session")
def sync_mongo_client():
    """Create a synchronous MongoDB client."""
    mongo_url = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
    client = MongoClient(mongo_url)
    yield client
    client.close()

@pytest.fixture(scope="session")
def async_mongo_client():
    """Create an asynchronous MongoDB client."""
    mongo_url = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
    client = AsyncIOMotorClient(mongo_url)
    yield client
    # Motor client doesn't need explicit closing

@pytest.fixture(scope="function")
async def test_db(event_loop, sync_mongo_client, async_mongo_client):
    """Setup test database."""
    # Use a separate test database
    mongo_db = "test_db"

    # Drop the database if it exists
    sync_mongo_client.drop_database(mongo_db)

    # Create new database connections
    async_db = async_mongo_client[mongo_db]
    sync_db = sync_mongo_client[mongo_db]

    # Set environment variable for tests
    os.environ["MONGO_DB"] = mongo_db

    # Create indexes for the test database
    await async_db.messages.create_index([("text", "text")])
    await async_db.messages.create_index([("conversation_id", 1)])
    await async_db.messages.create_index([("ts", 1)])
    await async_db.conversations.create_index([("channel_id", 1)], unique=True)
    await async_db.uploads.create_index([("created_at", -1)])

    # Set up the app with the test database
    app.db = async_db
    app.sync_db = sync_db
    app.service = MainService(db=async_db, sync_db=sync_db)

    yield async_db

    # Clean up
    sync_mongo_client.drop_database(mongo_db)

@pytest.fixture(scope="function")
def clean_directories(upload_dir, extract_dir):
    """Clean the upload and extract directories."""
    # Create a test subdirectory to isolate test files
    test_upload_dir = os.path.join(upload_dir, "test")
    test_extract_dir = os.path.join(extract_dir, "test")

    os.makedirs(test_upload_dir, exist_ok=True)
    os.makedirs(test_extract_dir, exist_ok=True)

    # Set environment variables to use test directories
    os.environ["UPLOAD_DIR"] = test_upload_dir
    os.environ["EXTRACT_DIR"] = test_extract_dir

    yield test_upload_dir, test_extract_dir

    # Clean up test directories after test
    if os.path.exists(test_upload_dir):
        shutil.rmtree(test_upload_dir)

    if os.path.exists(test_extract_dir):
        shutil.rmtree(test_extract_dir)

@pytest.fixture
def mock_slack_data():
    """
    Create standardized mock Slack data for testing.

    Returns a dictionary with test data that can be used across different tests.
    This centralizes test data creation to avoid duplication and inconsistency.
    """
    return {
        "channels": [
            {
                "name": "general",
                "id": "C12345",
                "topic": "General discussion",
                "purpose": "Company-wide announcements and work-based matters",
                "messages": [
                    {"user": "user1", "text": "Hello everyone!", "ts": "2023-01-01 10:00:00"},
                    {"user": "user2", "text": "Hi there!", "ts": "2023-01-01 10:01:00"},
                    {"user": "user3", "text": "Good morning team", "ts": "2023-01-01 10:02:00"}
                ]
            },
            {
                "name": "random",
                "id": "C67890",
                "topic": "Random stuff",
                "purpose": "Non-work banter and water cooler conversation",
                "messages": [
                    {"user": "user1", "text": "Check out this cool article", "ts": "2023-01-02 11:00:00"},
                    {"user": "user3", "text": "Thanks for sharing!", "ts": "2023-01-02 11:05:00"}
                ]
            }
        ],
        "dms": [
            {
                "users": ["user1", "user2"],
                "id": "D12345",
                "messages": [
                    {"user": "user1", "text": "Hey, do you have a minute?", "ts": "2023-01-03 09:00:00"},
                    {"user": "user2", "text": "Sure, what's up?", "ts": "2023-01-03 09:01:00"},
                    {"user": "user1", "text": "I need help with the project", "ts": "2023-01-03 09:02:00"}
                ]
            }
        ]
    }

@pytest.fixture
def create_test_slack_export(tmp_path, mock_slack_data):
    """
    Factory fixture that creates a test Slack export zip file.

    This fixture returns a function that can be called to create a test export
    with customizable data, allowing tests to create specific test scenarios.
    """
    def _create_export(data=None):
        if data is None:
            data = mock_slack_data

        # Create export directory
        export_dir = tmp_path / "slack_export"
        export_dir.mkdir(exist_ok=True)

        # Create the export files based on the provided data
        _create_channel_files(export_dir, data["channels"])
        _create_dm_files(export_dir, data["dms"])

        # Create zip file
        zip_path = tmp_path / "slack_export.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for file_path in export_dir.glob("*.txt"):
                zf.write(file_path, file_path.name)

        return zip_path

    return _create_export

# Helper functions for creating test files
def _create_channel_files(export_dir, channels):
    """Create channel files for test Slack export."""
    for channel in channels:
        channel_file = export_dir / f"{channel['name']}.txt"
        with open(channel_file, "w") as f:
            f.write(f"Channel Name: #{channel['name']}\n")
            f.write(f"Channel ID: {channel['id']}\n")
            f.write(f"Created: 2023-01-01 00:00:00 UTC by admin\n")
            f.write(f"Type: Channel\n")
            f.write(f"Topic: \"{channel['topic']}\", set on 2023-01-01 00:00:00 UTC by admin\n")
            f.write(f"Purpose: \"{channel['purpose']}\", set on 2023-01-01 00:00:00 UTC by admin\n")
            f.write("\n#################################################################\n\n")
            f.write("Messages:\n\n")

            # Group messages by date
            dates = {}
            for msg in channel["messages"]:
                date = msg["ts"].split()[0]
                if date not in dates:
                    dates[date] = []
                dates[date].append(msg)

            # Write messages by date
            for date, messages in dates.items():
                f.write(f"---- {date} ----\n")
                for msg in messages:
                    f.write(f"[{msg['ts']} UTC] <{msg['user']}> {msg['text']}\n")

def _create_dm_files(export_dir, dms):
    """Create DM files for test Slack export."""
    for dm in dms:
        dm_file = export_dir / f"{dm['id']}.txt"
        with open(dm_file, "w") as f:
            f.write(f"Private conversation between {', '.join(dm['users'])}\n")
            f.write(f"Channel ID: {dm['id']}\n")
            f.write(f"Created: 2023-01-01 00:00:00 UTC\n")
            f.write(f"Type: Direct Message\n")
            f.write("\n#################################################################\n\n")
            f.write("Messages:\n\n")

            # Group messages by date
            dates = {}
            for msg in dm["messages"]:
                date = msg["ts"].split()[0]
                if date not in dates:
                    dates[date] = []
                dates[date].append(msg)

            # Write messages by date
            for date, messages in dates.items():
                f.write(f"---- {date} ----\n")
                for msg in messages:
                    f.write(f"[{msg['ts']} UTC] <{msg['user']}> {msg['text']}\n")

@pytest.fixture
def mock_embeddings_service():
    """
    Create a mock embeddings service for testing search functionality.

    This centralizes the mocking logic to ensure consistency across tests.
    """
    with patch("app.services.search_service.EmbeddingService") as mock_embeddings:
        mock_instance = mock_embeddings.return_value
        mock_instance.search.return_value = [
            {
                "text": "Hello everyone!",
                "metadata": {"conversation_id": "C12345", "user": "user1", "timestamp": "1672567200.0"},
                "similarity": 0.9
            }
        ]
        yield mock_instance

@pytest.fixture(scope="function")
def test_slack_export(clean_directories):
    """Create a test Slack export with multiple channels and messages."""
    test_upload_dir, _ = clean_directories

    # Create a temporary directory for the export files
    export_dir = os.path.join(test_upload_dir, "slack_export")
    os.makedirs(export_dir, exist_ok=True)

    # Create channel files
    channels = [
        {
            "name": "general",
            "id": "C12345",
            "topic": "General discussion",
            "purpose": "Company-wide announcements and work-based matters",
            "messages": [
                {"user": "user1", "text": "Hello everyone!", "ts": "2023-01-01 10:00:00"},
                {"user": "user2", "text": "Hi there!", "ts": "2023-01-01 10:01:00"},
                {"user": "user3", "text": "Good morning team", "ts": "2023-01-01 10:02:00"}
            ]
        },
        {
            "name": "random",
            "id": "C67890",
            "topic": "Random stuff",
            "purpose": "Non-work banter and water cooler conversation",
            "messages": [
                {"user": "user1", "text": "Check out this cool article", "ts": "2023-01-02 11:00:00"},
                {"user": "user3", "text": "Thanks for sharing!", "ts": "2023-01-02 11:05:00"}
            ]
        }
    ]

    # Create DM conversations
    dms = [
        {
            "users": ["user1", "user2"],
            "id": "D12345",
            "messages": [
                {"user": "user1", "text": "Hey, do you have a minute?", "ts": "2023-01-03 09:00:00"},
                {"user": "user2", "text": "Sure, what's up?", "ts": "2023-01-03 09:01:00"},
                {"user": "user1", "text": "I need help with the project", "ts": "2023-01-03 09:02:00"}
            ]
        }
    ]

    # Write channel files
    for channel in channels:
        channel_file = os.path.join(export_dir, f"{channel['name']}.txt")
        with open(channel_file, "w") as f:
            f.write(f"Channel Name: #{channel['name']}\n")
            f.write(f"Channel ID: {channel['id']}\n")
            f.write(f"Created: 2023-01-01 00:00:00 UTC by admin\n")
            f.write(f"Type: Channel\n")
            f.write(f"Topic: \"{channel['topic']}\", set on 2023-01-01 00:00:00 UTC by admin\n")
            f.write(f"Purpose: \"{channel['purpose']}\", set on 2023-01-01 00:00:00 UTC by admin\n")
            f.write("\n#################################################################\n\n")
            f.write("Messages:\n\n")

            # Group messages by date
            dates = {}
            for msg in channel["messages"]:
                date = msg["ts"].split()[0]
                if date not in dates:
                    dates[date] = []
                dates[date].append(msg)

            # Write messages by date
            for date, messages in dates.items():
                f.write(f"---- {date} ----\n")
                for msg in messages:
                    f.write(f"[{msg['ts']} UTC] <{msg['user']}> {msg['text']}\n")

    # Write DM files
    for dm in dms:
        dm_file = os.path.join(export_dir, f"{dm['id']}.txt")
        with open(dm_file, "w") as f:
            f.write(f"Private conversation between {', '.join(dm['users'])}\n")
            f.write(f"Channel ID: {dm['id']}\n")
            f.write(f"Created: 2023-01-01 00:00:00 UTC\n")
            f.write(f"Type: Direct Message\n")
            f.write("\n#################################################################\n\n")
            f.write("Messages:\n\n")

            # Group messages by date
            dates = {}
            for msg in dm["messages"]:
                date = msg["ts"].split()[0]
                if date not in dates:
                    dates[date] = []
                dates[date].append(msg)

            # Write messages by date
            for date, messages in dates.items():
                f.write(f"---- {date} ----\n")
                for msg in messages:
                    f.write(f"[{msg['ts']} UTC] <{msg['user']}> {msg['text']}\n")

    # Create zip file
    zip_path = os.path.join(test_upload_dir, "slack_export.zip")
    import zipfile
    with zipfile.ZipFile(zip_path, "w") as zf:
        for root, _, files in os.walk(export_dir):
            for file in files:
                file_path = os.path.join(root, file)
                zf.write(file_path, os.path.relpath(file_path, export_dir))

    return zip_path
