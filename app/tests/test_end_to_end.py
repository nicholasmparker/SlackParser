"""End-to-end tests for the SlackParser application."""

import os
import zipfile
import shutil
import time
from pathlib import Path
from datetime import datetime
import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient
from motor.motor_asyncio import AsyncIOMotorClient
from unittest.mock import patch, MagicMock
import asyncio

from app.new_main import app
from app.services.main_service import MainService

# Create a test client as a fixture that depends on test_db
@pytest.fixture
async def client(test_db):
    """Create a test client with a properly configured app."""
    # Ensure app has the service attribute set
    # Note: test_db fixture already sets app.db and app.sync_db
    app.service = MainService(db=app.db, sync_db=app.sync_db)

    # Create a test client with a custom startup event handler
    # We need to patch the get_db function to prevent it from being awaited
    with patch('app.new_main.get_db') as mock_get_db:
        # Make the mock return the existing database
        mock_get_db.return_value = app.db

        # Use the TestClient with the patched get_db
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client

@pytest.mark.asyncio
@pytest.mark.e2e
async def test_full_pipeline(client, test_db, clean_directories, create_test_slack_export):
    """Test the full pipeline from upload to search."""
    # Create test data
    test_slack_export = create_test_slack_export()
    test_upload_dir, test_extract_dir = clean_directories

    # 1. Upload the file
    with open(test_slack_export, "rb") as f:
        response = client.post(
            "/upload",
            files={"file": ("slack_export.zip", f, "application/zip")}
        )

    assert response.status_code == 200
    upload_id = response.json()["id"]

    # 2. Extract the file
    response = client.post(f"/extract/{upload_id}")
    assert response.status_code == 200

    # Wait for extraction to complete
    max_retries = 10
    for _ in range(max_retries):
        upload = await test_db.uploads.find_one({"_id": upload_id})
        if upload and upload["status"] == "EXTRACTED":
            break
        time.sleep(0.5)

    assert upload["status"] == "EXTRACTED"

    # 3. Import the data
    response = client.post(f"/import/{upload_id}")
    assert response.status_code == 200

    # Wait for import to complete
    for _ in range(max_retries):
        upload = await test_db.uploads.find_one({"_id": upload_id})
        if upload and upload["status"] == "IMPORTED":
            break
        time.sleep(0.5)

    assert upload["status"] == "IMPORTED"

    # 4. Verify data was imported correctly
    # Check conversations
    channels = await test_db.conversations.find({"type": "channel"}).to_list(length=10)
    assert len(channels) == 2

    dms = await test_db.conversations.find({"type": "dm"}).to_list(length=10)
    assert len(dms) == 1

    # Check messages
    messages = await test_db.messages.find().to_list(length=100)
    assert len(messages) == 8  # Total messages from all channels and DMs

    # 5. Test search functionality
    with patch("app.services.search_service.EmbeddingService") as mock_embeddings_service:
        # Configure mock
        mock_embeddings_service.return_value.search.return_value = [
            {"text": "Hello everyone!", "metadata": {"conversation_id": "C12345", "user": "user1", "timestamp": "1672567200.0"}, "similarity": 0.9}
        ]

        # Test API search endpoint
        # Test API search endpoint
        response = client.post(
            "/api/v1/search",
            json={"query": "hello", "hybrid_alpha": 0.5, "limit": 10}
        )
        assert response.status_code == 200
        results = response.json()
        assert len(results["results"]) == 1
        assert results["results"][0]["text"] == "Hello everyone!"

@pytest.mark.asyncio
@pytest.mark.e2e
async def test_error_handling(client, test_db, clean_directories, tmp_path):
    """Test error handling in the pipeline with an invalid zip file."""
    # Create an invalid zip file
    invalid_zip = tmp_path / "invalid.zip"
    with open(invalid_zip, "wb") as f:
        f.write(b"This is not a valid ZIP file")

    # 1. Upload the invalid file
    with open(invalid_zip, "rb") as f:
        response = client.post(
            "/upload",
            files={"file": ("invalid.zip", f, "application/zip")}
        )

    assert response.status_code == 200  # Upload should succeed
    upload_id = response.json()["id"]

    # 2. Try to extract the invalid file
    response = client.post(f"/extract/{upload_id}")
    assert response.status_code == 200  # API call succeeds but extraction will fail

    # Wait for extraction to fail
    max_retries = 10
    for _ in range(max_retries):
        upload = await test_db.uploads.find_one({"_id": upload_id})
        if upload["status"] == "ERROR":
            break
        time.sleep(0.5)

    assert upload["status"] == "ERROR"
    assert "error" in upload

@pytest.mark.asyncio
@pytest.mark.e2e
async def test_empty_export_handling(client, test_db, clean_directories, tmp_path):
    """Test handling of an empty export file."""
    # Create an empty zip file
    empty_zip = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty_zip, "w"):
        pass  # Create empty zip

    # Upload the empty file
    with open(empty_zip, "rb") as f:
        response = client.post(
            "/upload",
            files={"file": ("empty.zip", f, "application/zip")}
        )

    assert response.status_code == 200
    upload_id = response.json()["id"]

    # Try to extract the empty file
    response = client.post(f"/extract/{upload_id}")
    assert response.status_code == 200

    # Wait for extraction to complete
    max_retries = 10
    for _ in range(max_retries):
        upload = await test_db.uploads.find_one({"_id": upload_id})
        if upload["status"] == "EXTRACTED" or upload["status"] == "ERROR":
            break
        time.sleep(0.5)

    # Try to import the empty export
    response = client.post(f"/import/{upload_id}")
    assert response.status_code == 200

    # Wait for import to complete or fail
    for _ in range(max_retries):
        upload = await test_db.uploads.find_one({"_id": upload_id})
        if upload["status"] == "IMPORTED" or upload["status"] == "ERROR":
            break
        time.sleep(0.5)
