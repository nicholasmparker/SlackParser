"""Tests for the Slack export importer functionality."""
import os
import pytest  # nosec
from unittest.mock import Mock, patch
from app.importer.importer import SlackImporter
from app.db.models import Upload

def test_extraction_progress_updates():
    """Test that extraction progress is properly tracked and updated."""
    # Mock dependencies
    db_mock = Mock()
    embedding_service_mock = Mock()

    # Create a test upload record
    upload = Upload(
        filename="test.zip",
        file_path="/path/to/test.zip",
        status="UPLOADED"
    )
    db_mock.get_upload.return_value = upload

    importer = SlackImporter(db_mock, embedding_service_mock)

    # Mock the zipfile extraction to simulate progress
    with patch('zipfile.ZipFile') as mock_zip:
        # Configure mock to simulate a zip with 100 files
        mock_zip.return_value.__enter__.return_value.namelist.return_value = [
            f"file_{i}.txt" for i in range(100)
        ]

        # Start the import process
        importer.start_import("test_upload_id")

        # Verify the upload status was updated to EXTRACTING
        db_mock.update_upload.assert_any_call(
            "test_upload_id",
            {"status": "EXTRACTING"}
        )

        # Verify progress updates were made during extraction
        progress_updates = [
            call[0][1].get('progress', '')
            for call in db_mock.update_upload.call_args_list
            if 'progress' in call[0][1]
        ]

        # Check that we got progress updates
        assert any('Extracting' in update for update in progress_updates)  # nosec
        assert any('%' in update for update in progress_updates)  # nosec

def test_extraction_error_handling():
    """Test that extraction errors are properly caught and reported."""
    db_mock = Mock()
    embedding_service_mock = Mock()

    upload = Upload(
        filename="test.zip",
        file_path="/nonexistent/test.zip",
        status="UPLOADED"
    )
    db_mock.get_upload.return_value = upload

    importer = SlackImporter(db_mock, embedding_service_mock)

    # Start import with a nonexistent file
    importer.start_import("test_upload_id")

    # Verify error status was set
    db_mock.update_upload.assert_any_call(
        "test_upload_id",
        {
            "status": "ERROR",
            "error": pytest.raises(FileNotFoundError)  # nosec
        }
    )
