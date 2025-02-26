"""Test conversation view functionality"""
import pytest
import unittest
from datetime import datetime
from app.main import app
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.mark.asyncio
class TestConversationView(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = TestClient(app)

        # Mock message data
        self.test_messages = [
            {
                "_id": "msg1",
                "conversation_id": "U7WB86M7W-noahv-nicole-casey-jenniferf",
                "user": "U7WB86M7W",
                "username": "noahv",  # Note: parser uses username
                "user_name": "noahv",  # Template uses user_name
                "text": "Test message 1",
                "ts": datetime(2024, 2, 25, 12, 0, 0),
                "type": "message",
                "timestamp": datetime(2024, 2, 25, 12, 0, 0)  # Pipeline uses timestamp
            },
            {
                "_id": "msg2",
                "conversation_id": "U7WB86M7W-noahv-nicole-casey-jenniferf",
                "user": "U123456",
                "username": "nicole",
                "user_name": "nicole",  # Template uses user_name
                "text": "Test message 2",
                "ts": datetime(2024, 2, 25, 12, 1, 0),
                "type": "message",
                "timestamp": datetime(2024, 2, 25, 12, 1, 0)  # Pipeline uses timestamp
            }
        ]

        # Mock conversation data
        self.test_conversation = {
            "_id": "U7WB86M7W-noahv-nicole-casey-jenniferf",
            "type": "dm",
            "name": "U7WB86M7W-noahv-nicole-casey-jenniferf",
            "display_name": "noahv, nicole, casey, jenniferf"
        }

        # Setup MongoDB mock
        app.db = MagicMock()
        app.db.conversations = MagicMock()
        app.db.messages = MagicMock()

    async def test_view_conversation(self):
        # Setup mock aggregations
        mock_conversation_agg = AsyncMock()
        mock_conversation_agg.__anext__.return_value = self.test_conversation
        app.db.conversations.aggregate.return_value = mock_conversation_agg

        mock_messages_agg = AsyncMock()
        mock_messages_agg.to_list.return_value = self.test_messages
        app.db.messages.aggregate.return_value = mock_messages_agg

        app.db.messages.count_documents = AsyncMock(return_value=2)

        # Test conversation view
        response = self.client.get("/conversation/U7WB86M7W-noahv-nicole-casey-jenniferf")

        # Check response
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"noahv", response.content)
        self.assertIn(b"Test message 1", response.content)
        self.assertIn(b"nicole", response.content)
        self.assertIn(b"Test message 2", response.content)
