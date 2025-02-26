"""
Test the parser module against exact formats from ARCHITECTURE.md
"""

import pytest
from datetime import datetime
from app.importer.parser import parse_channel_metadata, parse_dm_metadata, parse_message, ParserError

def test_channel_metadata():
    """Test parsing channel metadata in the exact format"""
    lines = [
        "Channel Name: #general",
        "Channel ID: C1234567890",
        "Created: 2023-01-01 12:00:00 UTC by johndoe",
        "Type: Channel",
        'Topic: "Welcome!", set on 2023-01-01 12:01:00 UTC by johndoe',
        'Purpose: "Company announcements", set on 2023-01-01 12:02:00 UTC by johndoe'
    ]
    
    channel = parse_channel_metadata(lines)
    assert channel.id == "C1234567890"
    assert channel.name == "general"
    assert channel.created == datetime(2023, 1, 1, 12, 0)
    assert channel.creator_username == "johndoe"
    assert channel.topic == "Welcome!"
    assert channel.topic_set_by == "johndoe"
    assert channel.topic_set_at == datetime(2023, 1, 1, 12, 1)
    assert channel.purpose == "Company announcements"
    assert channel.purpose_set_by == "johndoe"
    assert channel.purpose_set_at == datetime(2023, 1, 1, 12, 2)
    assert not channel.is_dm

def test_dm_metadata():
    """Test parsing DM metadata in the exact format"""
    lines = [
        "Private conversation between user1, user2",
        "Channel ID: D1234567890",
        "Created: 2023-01-01 12:00:00 UTC",
        "Type: Direct Message"
    ]
    
    channel = parse_dm_metadata(lines)
    assert channel.id == "D1234567890"
    assert channel.name == "DM: user1-user2"
    assert channel.created == datetime(2023, 1, 1, 12, 0)
    assert channel.is_dm
    assert channel.dm_users == ["user1", "user2"]

def test_regular_message():
    """Test parsing regular message format"""
    line = "[2023-01-01 12:00:00 UTC] <johndoe> Hello world"
    msg = parse_message(line, 1)
    assert msg.username == "johndoe"
    assert msg.text == "Hello world"
    assert msg.type == "message"
    assert msg.ts == datetime(2023, 1, 1, 12, 0)

def test_edited_message():
    """Test parsing edited message format"""
    line = "[2023-01-01 12:00:00 UTC] <johndoe> Hello world (edited)"
    msg = parse_message(line, 1)
    assert msg.username == "johndoe"
    assert msg.text == "Hello world"
    assert msg.type == "message"
    assert msg.is_edited

def test_join_message():
    """Test parsing join message format"""
    line = "[2023-01-01 12:00:00 UTC] johndoe joined the channel"
    msg = parse_message(line, 1)
    assert msg.username == "johndoe"
    assert msg.text == "joined the channel"
    assert msg.type == "system"
    assert msg.system_action == "joined"

def test_archive_message():
    """Test parsing archive message format"""
    line = '[2023-01-01 12:00:00 UTC] (channel_archive) <johndoe> {"user":"U123","text":"archived the channel"}'
    msg = parse_message(line, 1)
    assert msg.username == "johndoe"
    assert msg.text == "archived the channel"
    assert msg.type == "archive"
    assert msg.system_action == "archive"

def test_file_share_message():
    """Test parsing file share message format"""
    line = "[2023-01-01 12:00:00 UTC] <johndoe> shared a file: report.pdf"
    msg = parse_message(line, 1)
    assert msg.username == "johndoe"
    assert msg.text == "report.pdf"
    assert msg.type == "file"
    assert msg.file_id == "report.pdf"

def test_invalid_message():
    """Test handling invalid message format"""
    line = "Not a valid message"
    msg = parse_message(line, 1)
    assert msg is None

def test_parser_error():
    """Test error handling with line numbers"""
    line = "[invalid timestamp] <user> text"
    with pytest.raises(ParserError) as exc:
        parse_message(line, 42)
    assert exc.value.line_number == 42
