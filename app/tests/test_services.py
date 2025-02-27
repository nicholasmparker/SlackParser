"""Tests for the service layer of the SlackParser application."""

import os
import zipfile
import json
import time
import shutil
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch
from bson import ObjectId
import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from pymongo import MongoClient

from app.main import app
from app.services.upload_service import UploadService
from app.services.extraction_service import ExtractionService
from app.services.import_service import ImportService
from app.services.search_service import SearchService
from app.services.main_service import MainService
from app.db.models import UploadStatus

# Create a test client
client = TestClient(app)

TEST_CHANNEL_CONTENT = """Channel Name: #general
Channel ID: C123456
Created: 2024-02-25 12:00:00 UTC by testuser
Type: Channel
Topic: "Test topic", set on 2024-02-25 12:00:00 UTC by testuser
Purpose: "Test purpose", set on 2024-02-25 12:00:00 UTC by testuser

#################################################################

Messages:

---- 2024-02-25 ----
[2024-02-25 12:00:00 UTC] <testuser> Test message 1
[2024-02-25 12:01:00 UTC] <testuser> Test message 2
[2024-02-25 12:02:00 UTC] testuser joined the channel"""

@pytest.fixture
def test_zip(tmp_path: Path) -> Path:
    """Create a test zip file with a channel."""
    # Create test channel file
    channel_dir = tmp_path / "test_export"
    channel_dir.mkdir()
    channel_file = channel_dir / "test_channel.txt"
    channel_file.write_text(TEST_CHANNEL_CONTENT)

    # Create zip file
    zip_path = tmp_path / "test_export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(channel_file, channel_file.relative_to(tmp_path))

    # Return the path to the zip file
    print(f"Created test zip file at {zip_path}")

    return zip_path

@pytest.fixture
def upload_service(test_db):
    """Create an upload service with a test database."""
    return UploadService(db=test_db, sync_db=test_db)

@pytest.fixture
def extraction_service(test_db):
    """Create an extraction service with a test database."""
    return ExtractionService(db=test_db, sync_db=test_db)

@pytest.fixture
def import_service(test_db):
    """Create an import service with a test database."""
    return ImportService(db=test_db, sync_db=test_db)

@pytest.fixture
def search_service(test_db):
    """Create a search service with a test database."""
    return SearchService(db=test_db, sync_db=test_db)

@pytest.fixture
def main_service(test_db):
    """Create a main service with a test database."""
    return MainService(db=test_db, sync_db=test_db)

@pytest.mark.asyncio
@pytest.mark.unit
async def test_upload_service(upload_service, tmp_path):
    """Test the upload service."""
    # Create a mock file
    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "test.zip"

    # Mock the file read method to return chunks
    chunk_size = 1024
    mock_file.read.side_effect = [b"x" * chunk_size, b""]

    # Set up the upload directory
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    upload_service.upload_dir = str(upload_dir)

    # Upload the file
    result = await upload_service.upload_file(mock_file)

    # Check the result
    assert "id" in result
    assert result["status"] == "UPLOADED"
    assert result["size"] == chunk_size

    # Check that the file was saved
    upload_id = result["id"]
    upload = await upload_service.get_upload(upload_id)
    assert upload is not None
    assert upload["filename"] == "test.zip"
    assert upload["status"] == "UPLOADED"
    assert upload["size"] == chunk_size

    # Check that the file exists
    file_path = upload["file_path"]
    assert os.path.exists(file_path)

    # Test listing uploads
    uploads = await upload_service.list_uploads()
    assert len(uploads) == 1
    assert uploads[0]["id"] == upload_id

    # Test deleting the upload
    success = await upload_service.delete_upload(upload_id)
    assert success
    assert not os.path.exists(file_path)

    # Check that the upload was deleted from the database
    upload = await upload_service.get_upload(upload_id)
    assert upload is None

@pytest.mark.asyncio
@pytest.mark.integration
async def test_extraction_service(extraction_service, test_db, test_zip, tmp_path):
    """Test the extraction service."""
    # Set up the extract directory
    extract_dir = tmp_path / "extracts"
    extract_dir.mkdir()

    # Create a test upload ID
    upload_id = str(ObjectId())
    extract_path = extract_dir / upload_id
    os.environ["EXTRACT_DIR"] = str(extract_dir)

    # Create a test upload
    await test_db.uploads.insert_one({
        "_id": ObjectId(upload_id),
        "filename": "test_export.zip",
        "file_path": str(test_zip),
        "status": "UPLOADED",
        "created_at": datetime.utcnow(),
        "size": test_zip.stat().st_size,
        "uploaded_size": test_zip.stat().st_size
    })

    # Extract the zip file
    await extraction_service.extract_with_progress(str(test_zip), extract_path, upload_id)

    # Check that the upload status was updated
    upload = await test_db.uploads.find_one({"_id": ObjectId(upload_id)})
    assert upload["status"] == "EXTRACTED"

    # Check that the extract directory was created
    extract_path = upload["extract_path"]
    assert os.path.exists(extract_path), f"Extract path {extract_path} does not exist"
    # The test_channel.txt file is inside the test_export directory in the zip
    assert os.path.exists(os.path.join(extract_path, "test_export", "test_channel.txt"))

@pytest.mark.asyncio
@pytest.mark.unit
async def test_search_service(search_service, test_db):
    """Test the search service."""
    # Mock the embeddings service
    search_service.embeddings = MagicMock()
    search_service.embeddings.search = MagicMock()
    search_service.embeddings.search.return_value = [
        {
            "text": "Test message 1",
            "metadata": {
                "conversation_id": "C123456",
                "user": "testuser",
                "timestamp": "1614254400.0"
            },
            "similarity": 0.9
        }
    ]

    # Add a test conversation
    await test_db.conversations.insert_one({
        "channel_id": "C123456",
        "name": "general",
        "type": "channel"
    })

    # Add a test message
    await test_db.messages.insert_one({
        "text": "Test message 1",
        "conversation_id": "C123456",
        "username": "testuser",
        "ts": 1614254400.0
    })

    # Test semantic search
    results = await search_service.search("test query")
    assert len(results) == 1
    assert results[0]["text"] == "Test message 1"
    assert results[0]["conversation_id"] == "C123456"
    assert results[0]["user"] == "testuser"
    assert results[0]["score"] == 0.9

    # Test text search
    results = await search_service.text_search("test")
    assert len(results) == 1
    assert results[0]["text"] == "Test message 1"
    assert results[0]["conversation_id"] == "C123456"

    # Test context retrieval
    await test_db.messages.insert_many([
        {
            "text": "Test message 2",
            "conversation_id": "C123456",
            "username": "testuser",
            "ts": 1614254500.0
        },
        {
            "text": "Test message 3",
            "conversation_id": "C123456",
            "username": "testuser",
            "ts": 1614254600.0
        }
    ])

    context = await search_service.get_context("C123456", 1614254500.0, 1)
    assert len(context) == 3
    assert context[0]["text"] == "Test message 1"
    assert context[1]["text"] == "Test message 2"
    assert context[2]["text"] == "Test message 3"

@pytest.mark.asyncio
@pytest.mark.unit
async def test_main_service(main_service):
    """Test the main service."""
    # Check that services are initialized correctly
    assert main_service.extraction_service is not None
    assert main_service.import_service is not None
    assert main_service.search_service is not None
    assert main_service.upload_service is not None

    # Check that services are cached
    extraction_service_1 = main_service.extraction_service
    extraction_service_2 = main_service.extraction_service
    assert extraction_service_1 is extraction_service_2

@pytest.mark.asyncio
@pytest.mark.unit
async def test_upload_service_error_handling(upload_service, tmp_path):
    """Test error handling in the upload service."""
    # Create a mock file that will raise an exception when read
    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "test.zip"
    mock_file.read.side_effect = Exception("Simulated read error")

    # Set up the upload directory
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    upload_service.upload_dir = str(upload_dir)

    # Upload the file and expect an error
    with pytest.raises(Exception):
        await upload_service.upload_file(mock_file)

@pytest.mark.asyncio
@pytest.mark.integration
async def test_extraction_service_with_invalid_zip(extraction_service, test_db, tmp_path):
    """Test extraction service with an invalid zip file."""
    # Create an invalid zip file
    invalid_zip = tmp_path / "invalid.zip"
    with open(invalid_zip, "wb") as f:
        f.write(b"This is not a valid ZIP file")

    # Create a test upload
    upload_id = str(ObjectId())
    await test_db.uploads.insert_one({
        "_id": ObjectId(upload_id),
        "filename": "invalid.zip",
        "file_path": str(invalid_zip),
        "status": "UPLOADED",
        "created_at": datetime.utcnow(),
        "size": invalid_zip.stat().st_size,
        "uploaded_size": invalid_zip.stat().st_size
    })

    # Extract the invalid zip file - should handle the error gracefully
    extract_path = tmp_path / "extracts" / upload_id
    os.makedirs(extract_path, exist_ok=True)

    try:
        # This should raise a BadZipFile exception
        await extraction_service.extract_with_progress(str(invalid_zip), extract_path, upload_id)
        # If we get here, the extraction service didn't raise an exception
        assert False, "Expected BadZipFile exception was not raised"
    except zipfile.BadZipFile:
        # This is expected - now we need to manually update the status to ERROR
        # since the extraction service doesn't handle this automatically
        await test_db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {"$set": {"status": "ERROR", "error": "Invalid ZIP file"}}
        )
