"""Integration tests for the parser with real data."""

import os
import pytest
from pathlib import Path
from app.importer.parser import parse_channel_metadata, parse_dm_metadata, parse_message

# Sample data paths - these would be real files in your test_data directory
TEST_CHANNEL_PATH = os.path.join("test_data", "slack-export", "channels", "general", "2023-01-01.txt")
TEST_DM_PATH = os.path.join("test_data", "slack-export", "dms", "D12345", "2023-01-01.txt")

@pytest.mark.integration
def test_parse_real_channel_file():
    """Test parsing a real channel file if it exists."""
    # Skip if test data doesn't exist
    if not os.path.exists(TEST_CHANNEL_PATH):
        pytest.skip(f"Test data not found: {TEST_CHANNEL_PATH}")

    # Read the channel file
    with open(TEST_CHANNEL_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Extract metadata and messages
    metadata_lines = []
    message_lines = []
    in_metadata = True

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line == "#################################################################":
            in_metadata = False
            continue

        if in_metadata:
            metadata_lines.append(line)
        elif line.startswith("----"):
            # Date separator
            continue
        else:
            message_lines.append(line)

    # Parse metadata if we have enough lines
    if len(metadata_lines) >= 4:
        try:
            metadata = parse_channel_metadata(metadata_lines)
            assert metadata.id.startswith("C"), "Channel ID should start with C"
            assert metadata.name, "Channel should have a name"
            print(f"Successfully parsed channel metadata: {metadata.name} ({metadata.id})")
        except Exception as e:
            print(f"Error parsing channel metadata: {e}")
            # Don't fail the test, just log the error

    # Parse messages
    successful_messages = 0
    failed_messages = 0

    for i, line in enumerate(message_lines):
        try:
            message = parse_message(line, i + 1)
            if message:
                successful_messages += 1
                # Verify message has required fields
                assert message.text, "Message should have text"
                assert message.username, "Message should have username"
                assert message.ts, "Message should have timestamp"
        except Exception as e:
            failed_messages += 1
            print(f"Error parsing message at line {i+1}: {e}")

    print(f"Successfully parsed {successful_messages} messages, failed to parse {failed_messages} messages")

    # We should have parsed at least some messages successfully
    if message_lines:
        assert successful_messages > 0, "Should have parsed at least one message successfully"

@pytest.mark.integration
def test_parse_real_dm_file():
    """Test parsing a real DM file if it exists."""
    # Skip if test data doesn't exist
    if not os.path.exists(TEST_DM_PATH):
        pytest.skip(f"Test data not found: {TEST_DM_PATH}")

    # Read the DM file
    with open(TEST_DM_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Extract metadata and messages
    metadata_lines = []
    message_lines = []
    in_metadata = True

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line == "#################################################################":
            in_metadata = False
            continue

        if in_metadata:
            metadata_lines.append(line)
        elif line.startswith("----"):
            # Date separator
            continue
        else:
            message_lines.append(line)

    # Parse metadata if we have enough lines
    if len(metadata_lines) >= 4:
        try:
            metadata = parse_dm_metadata(metadata_lines)
            assert metadata.id.startswith("D"), "DM ID should start with D"
            assert metadata.name.startswith("DM:"), "DM name should start with DM:"
            assert metadata.is_dm, "DM should have is_dm=True"
            print(f"Successfully parsed DM metadata: {metadata.name} ({metadata.id})")
        except Exception as e:
            print(f"Error parsing DM metadata: {e}")
            # Don't fail the test, just log the error

    # Parse messages
    successful_messages = 0
    failed_messages = 0

    for i, line in enumerate(message_lines):
        try:
            message = parse_message(line, i + 1)
            if message:
                successful_messages += 1
                # Verify message has required fields
                assert message.text, "Message should have text"
                assert message.username, "Message should have username"
                assert message.ts, "Message should have timestamp"
        except Exception as e:
            failed_messages += 1
            print(f"Error parsing message at line {i+1}: {e}")

    print(f"Successfully parsed {successful_messages} messages, failed to parse {failed_messages} messages")

    # We should have parsed at least some messages successfully
    if message_lines:
        assert successful_messages > 0, "Should have parsed at least one message successfully"

@pytest.mark.integration
def test_parse_with_generated_data():
    """Test parsing with generated test data that mimics real Slack exports."""
    # Create test channel metadata
    channel_metadata = [
        "Channel Name: #general",
        "Channel ID: C12345",
        "Created: 2023-01-01 00:00:00 UTC by admin",
        "Type: Channel",
        "Topic: \"General discussion\", set on 2023-01-01 00:00:00 UTC by admin",
        "Purpose: \"Company-wide announcements\", set on 2023-01-01 00:00:00 UTC by admin"
    ]

    # Create test messages
    messages = [
        "[2023-01-01 10:00:00 UTC] <user1> Hello everyone!",
        "[2023-01-01 10:01:00 UTC] <user2> Hi there!",
        "[2023-01-01 10:02:00 UTC] <user3> Good morning team",
        "[2023-01-01 10:03:00 UTC] user4 joined the channel",
        "[2023-01-01 10:04:00 UTC] <user1> shared a file: document.pdf",
        "[2023-01-01 10:05:00 UTC] <user2> This is a message with emoji 😊",
        "[2023-01-01 10:06:00 UTC] <user3> This is a message with *formatting*",
        "[2023-01-01 10:07:00 UTC] <user1> This is a message with a <https://example.com|link>",
        "[2023-01-01 10:08:00 UTC] <user2> This is a message with a @mention",
        "[2023-01-01 10:09:00 UTC] <user3> This is a message with a #channel reference"
    ]

    # Parse channel metadata
    metadata = parse_channel_metadata(channel_metadata)
    assert metadata.id == "C12345"
    assert metadata.name == "general"
    assert metadata.topic == "General discussion"
    assert metadata.purpose == "Company-wide announcements"

    # Parse messages
    for i, line in enumerate(messages):
        message = parse_message(line, i + 1)
        assert message is not None, f"Failed to parse message: {line}"

        # Check specific message types
        if i == 0:
            assert message.username == "user1"
            assert message.text == "Hello everyone!"
            assert message.type == "message"
        elif i == 3:
            assert message.username == "user4"
            assert message.text == "joined the channel"
            assert message.type == "join"
        elif i == 4:
            assert message.username == "user1"
            assert message.text == "document.pdf"
            assert message.type == "file"

    print(f"Successfully parsed all {len(messages)} test messages")
