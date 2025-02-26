"""Test import functionality"""
import os
import re
from pathlib import Path
from datetime import datetime
import pytest
from app.slack_parser import parse_message_line, parse_dm_metadata, parse_channel_metadata

@pytest.mark.asyncio
async def test_import_channel_or_dm(tmp_path: Path) -> tuple[int, list[str]]:
    """Test parsing a channel file"""
    messages = 0
    errors = []

    # Create test channel file
    channel_file = tmp_path / "test_channel.txt"
    channel_file.write_text("""Channel Name: #general
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
[2024-02-25 12:02:00 UTC] testuser joined the channel""")

    try:
        # Parse the file
        lines = channel_file.read_text().splitlines()

        # Find separator
        separator_idx = lines.index("#################################################################")

        # Parse metadata
        header_lines = lines[:separator_idx]
        metadata = parse_channel_metadata(header_lines)
        if metadata["name"] != "general":
            errors.append(f"Expected channel name 'general', got '{metadata['name']}'")
        if metadata["id"] != "C123456":
            errors.append(f"Expected channel ID 'C123456', got '{metadata['id']}'")

        # Parse messages
        message_types = {}
        in_messages = False
        for line in lines[separator_idx:]:
            line = line.strip()
            if not line:
                continue

            if line == "Messages:":
                in_messages = True
                continue

            if not in_messages:
                continue

            if line.startswith("----"):
                continue

            message = parse_message_line(line)
            if message:
                messages += 1
                msg_type = message["type"]
                message_types[msg_type] = message_types.get(msg_type, 0) + 1

        # Verify message counts
        if messages != 3:
            errors.append(f"Expected 3 messages, got {messages}")
        if message_types.get("message", 0) != 2:
            errors.append(f"Expected 2 regular messages, got {message_types.get('message', 0)}")
        if message_types.get("join", 0) != 1:
            errors.append(f"Expected 1 join message, got {message_types.get('join', 0)}")

    except Exception as e:
        error = f"Error parsing {channel_file}: {str(e)}"
        errors.append(error)

    return messages, errors

@pytest.mark.asyncio
async def test_import(tmp_path: Path):
    """Test the full import process"""
    messages, errors = await test_import_channel_or_dm(tmp_path)
    if messages != 3:
        pytest.fail(f"Expected 3 messages, got {messages}")
    if errors:
        pytest.fail(f"Encountered errors: {errors}")
