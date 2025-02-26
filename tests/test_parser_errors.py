"""Test error cases in the parser."""

import pytest
from app.importer.parser import parse_message, ParserError

def test_bot_message_with_int_values():
    """Test bot message with integer values in JSON."""
    # The actual message that's failing
    line = '[2023-01-03 16:54:29 UTC] [<DoseSpot> bot] {"code":"invalid","diagnostics":"Bad request to add patient to dosespot, Patient sex at birth is missing"}'

    # This should not raise an error
    message = parse_message(line, 1)
    assert message is not None
    assert message.username == "DoseSpot"
    assert message.is_bot is True

def test_archive_message_with_int_user():
    """Test archive message with integer user ID."""
    line = '[2023-01-03 16:54:29 UTC] (channel_archive) <user123> {"user": 12345, "text": "archived the channel"}'

    # This should not raise an error
    message = parse_message(line, 1)
    assert message is not None
    assert message.type == "channel_archive"
    assert isinstance(message.data["user"], dict)
    assert message.data["user"]["id"] == "12345"

def test_message_with_int_values():
    """Test message with integer values in JSON."""
    line = '[2023-01-03 16:54:29 UTC] <user123> {"count": 42, "enabled": true}'

    # This should not raise an error
    message = parse_message(line, 1)
    assert message is not None
    assert message.type == "message"
    assert isinstance(message.data["count"], str)
    assert message.data["count"] == "42"
