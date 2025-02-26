"""Test the import pipeline stages"""
import os
import zipfile
from pathlib import Path
from datetime import datetime
from bson import ObjectId
import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

from app.main import app
from app.db.models import UploadStatus

# Create a test client that will be used for all tests
client = TestClient(app)

@pytest.fixture
def test_db():
    """Setup test database"""
    mongo_url = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
    mongo_db = os.getenv("MONGO_DB", "test_db")
    
    # Create DB connection
    mongo_client = MongoClient(mongo_url)
    db = mongo_client[mongo_db]
    
    # Clear existing data
    mongo_client.drop_database(mongo_db)
    
    # Set the db on the app
    app.db = db
    
    yield db
    
    # Cleanup after test
    mongo_client.drop_database(mongo_db)

@pytest.fixture
def test_zip(tmp_path: Path) -> Path:
    """Create a test zip file with a channel"""
    # Create test channel file
    channel_dir = tmp_path / "test_export"
    channel_dir.mkdir()
    channel_file = channel_dir / "test_channel.txt"
    channel_file.write_text("""Channel Name: #general
Channel ID: C123456
Created: 2024-02-25 12:00:00 UTC by testuser
Type: Channel

#################################################################

Messages:

---- 2024-02-25 ----
[2024-02-25 12:00:00 UTC] <testuser> Test message""")

    # Create zip file
    zip_path = tmp_path / "test_export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(channel_file, channel_file.relative_to(tmp_path))

    return zip_path

def test_pipeline_stages(test_db, test_zip, tmp_path):
    """Test that the pipeline progresses through stages correctly"""
    # Setup extraction directory
    extract_dir = tmp_path / "extracts"
    extract_dir.mkdir()
    os.environ["EXTRACT_DIR"] = str(extract_dir)

    # Create test upload
    upload_id = ObjectId()
    test_db.uploads.insert_one({
        "_id": upload_id,
        "filename": "test_export.zip",
        "file_path": str(test_zip),
        "status": UploadStatus.UPLOADED,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "size": test_zip.stat().st_size,
        "uploaded_size": test_zip.stat().st_size,
        "progress": "Upload complete",
        "progress_percent": 100
    })

    # Start the import
    response = client.post(f"/admin/import/{str(upload_id)}/start")
    assert response.status_code == 200

    # Check status progresses correctly
    status = client.get(f"/admin/import/{str(upload_id)}/status").json()
    assert status["status"] in [UploadStatus.EXTRACTING.value, UploadStatus.EXTRACTED.value, 
                               UploadStatus.IMPORTING.value, UploadStatus.IMPORTED.value,
                               UploadStatus.EMBEDDING.value, UploadStatus.COMPLETE.value]
    
    # Verify data was imported (or will be)
    upload = test_db.uploads.find_one({"_id": upload_id})
    assert upload is not None
    assert upload["status"] != UploadStatus.ERROR.value

def test_pipeline_error_handling(test_db, tmp_path):
    """Test that the pipeline handles errors correctly"""
    # Create test upload with invalid zip
    upload_id = ObjectId()
    invalid_zip = tmp_path / "invalid.zip"
    invalid_zip.write_bytes(b"not a zip file")
    
    test_db.uploads.insert_one({
        "_id": upload_id,
        "filename": "invalid.zip",
        "file_path": str(invalid_zip),
        "status": UploadStatus.UPLOADED,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "size": invalid_zip.stat().st_size,
        "uploaded_size": invalid_zip.stat().st_size,
        "progress": "Upload complete",
        "progress_percent": 100
    })

    # Start the import - expect a 500 error since it's an invalid zip
    response = client.post(f"/admin/import/{str(upload_id)}/start")
    
    # Check if the status was updated to ERROR in the database
    upload = test_db.uploads.find_one({"_id": upload_id})
    assert upload["status"] == UploadStatus.ERROR.value
    assert "File is not a zip file" in upload.get("error", "")
