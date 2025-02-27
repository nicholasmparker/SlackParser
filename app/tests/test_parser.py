"""Tests for the Slack message parser."""

import pytest
from app.importer.parser import parse_channel_metadata, parse_dm_metadata, parse_message
from datetime import datetime

def test_parse_channel_metadata():
    """Test parsing channel metadata."""
    lines = [
        "Channel Name: #general",
        "Channel ID: C12345",
        "Created: 2023-01-01 00:00:00 UTC by admin",
        "Type: Channel",
        "Topic: \"General discussion\", set on 2023-01-01 00:00:00 UTC by admin",
        "Purpose: \"Company-wide announcements\", set on 2023-01-01 00:00:00 UTC by admin"
    ]

    metadata = parse_channel_metadata(lines)

    assert metadata.name == "general"
    assert metadata.id == "C12345"
    assert metadata.topic == "General discussion"
    assert metadata.purpose == "Company-wide announcements"

def test_parse_dm_metadata():
    """Test parsing DM metadata."""
    lines = [
        "Private conversation between user1, user2",
        "Channel ID: D12345",
        "Created: 2023-01-01 00:00:00 UTC",
        "Type: Direct Message"
    ]

    metadata = parse_dm_metadata(lines)

    assert metadata.name == "DM: user1-user2"
    assert metadata.id == "D12345"
    assert metadata.is_dm == True

def test_parse_regular_message():
    """Test parsing a regular message."""
    line = "[2023-01-01 10:00:00 UTC] <user1> Hello world"

    message = parse_message(line, 1)

    assert message is not None
    assert message.text == "Hello world"
    assert message.username == "user1"
    assert message.ts.year == 2023
    assert message.ts.month == 1
    assert message.ts.day == 1
    assert message.ts.hour == 10
    assert message.ts.minute == 0
    assert message.type == "message"

def test_parse_join_message():
    """Test parsing a join message."""
    line = "[2023-01-01 10:00:00 UTC] user1 joined the channel"

    message = parse_message(line, 1)

    assert message is not None
    assert message.text == "joined the channel"
    assert message.username == "user1"
    assert message.ts.year == 2023
    assert message.ts.month == 1
    assert message.ts.day == 1
    assert message.ts.hour == 10
    assert message.ts.minute == 0
    assert message.type == "join"

def test_parse_archive_message():
    """Test parsing an archive message."""
    line = '[2023-01-01 10:00:00 UTC] (channel_archive) <user1> {"user":123,"text":"archived the channel"}'

    message = parse_message(line, 1)

    assert message is not None
    assert "archived the channel" in message.text
    assert message.username == "user1"
    assert message.ts.year == 2023
    assert message.ts.month == 1
    assert message.ts.day == 1
    assert message.ts.hour == 10
    assert message.ts.minute == 0
    assert message.type == "archive"

def test_parse_file_share_message():
    """Test parsing a file share message."""
    line = "[2023-01-01 10:00:00 UTC] <user1> shared a file: document.pdf"

    message = parse_message(line, 1)

    assert message is not None
    assert message.text == "document.pdf"
    assert message.username == "user1"
    assert message.ts.year == 2023
    assert message.ts.month == 1
    assert message.ts.day == 1
    assert message.ts.hour == 10
    assert message.ts.minute == 0
    assert message.type == "file"

def test_parse_system_message():
    """Test parsing a system message."""
    line = "[2023-01-01 10:00:00 UTC] This channel has been archived"

    message = parse_message(line, 1)

    assert message is not None
    assert message.text == "channel has been archived"
    assert message.username == "This"
    assert message.ts.year == 2023
    assert message.ts.month == 1
    assert message.ts.day == 1
    assert message.ts.hour == 10
    assert message.ts.minute == 0
    assert message.type == "system"

def test_parse_invalid_message():
    """Test parsing an invalid message."""
    line = "This is not a valid message format"

    message = parse_message(line, 1)

    assert message is None
