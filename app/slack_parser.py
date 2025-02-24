"""
Slack message parser that handles various message formats and cleans up the text
for better readability and embedding.
"""
import json
import re
from typing import Dict, Any, Optional, List
from datetime import datetime
from bs4 import BeautifulSoup
import html

class SlackMessageParser:
    @staticmethod
    def clean_html(text: str) -> str:
        """Remove HTML tags and decode HTML entities"""
        # First decode HTML entities
        text = html.unescape(text)
        
        # Parse with BeautifulSoup to remove HTML tags
        soup = BeautifulSoup(text, 'html.parser')
        return soup.get_text()
    
    @staticmethod
    def clean_slack_formatting(text: str) -> str:
        """Remove Slack-specific formatting markers"""
        # Remove user mentions
        text = re.sub(r'<@[A-Z0-9]+>', '', text)
        
        # Remove channel mentions
        text = re.sub(r'<#[A-Z0-9]+\|([^>]+)>', r'#\1', text)
        
        # Convert URLs to readable format
        text = re.sub(r'<(https?://[^|>]+)\|([^>]+)>', r'\2 (\1)', text)
        text = re.sub(r'<(https?://[^>]+)>', r'\1', text)
        
        # Remove any remaining angle brackets
        text = re.sub(r'[<>]', '', text)
        
        return text.strip()
    
    @staticmethod
    def extract_blocks_text(blocks: List[Dict[str, Any]]) -> str:
        """Extract text from Slack message blocks"""
        texts = []
        
        for block in blocks:
            if block.get("type") == "rich_text":
                for element in block.get("elements", []):
                    if element.get("type") == "rich_text_section":
                        for text_element in element.get("elements", []):
                            if text_element.get("type") in ["text", "user"]:
                                text = text_element.get("text", "")
                                texts.append(text)
            elif "text" in block:
                # Handle plain text blocks
                if isinstance(block["text"], str):
                    texts.append(block["text"])
                elif isinstance(block["text"], dict):
                    texts.append(block["text"].get("text", ""))
        
        return " ".join(texts)
    
    @staticmethod
    def parse_message(message: Dict[str, Any]) -> Dict[str, Any]:
        """Parse a Slack message and return cleaned data"""
        parsed = {
            "id": message.get("client_msg_id", message.get("ts", "")),
            "timestamp": message.get("ts", ""),
            "user": message.get("user", ""),
            "team": message.get("team", ""),
            "channel": message.get("channel", ""),
            "channel_type": message.get("channel_type", ""),
            "thread_ts": message.get("thread_ts"),
            "reply_count": message.get("reply_count", 0),
            "reply_users_count": message.get("reply_users_count", 0),
            "reactions": message.get("reactions", []),
        }
        
        # Get the message text
        text = ""
        
        # Try to get text from blocks first
        if "blocks" in message:
            text = SlackMessageParser.extract_blocks_text(message["blocks"])
        
        # Fallback to raw text if blocks parsing failed
        if not text and "text" in message:
            text = message["text"]
        
        # Clean the text
        if text:
            text = SlackMessageParser.clean_html(text)
            text = SlackMessageParser.clean_slack_formatting(text)
        
        parsed["text"] = text
        
        # Add user info if available
        if "user_profile" in message:
            profile = message["user_profile"]
            parsed["user_name"] = profile.get("real_name", "")
            parsed["user_email"] = profile.get("email", "")
            parsed["user_title"] = profile.get("title", "")
            
        # Add thread/parent message context if available
        if message.get("parent_message"):
            parent = message["parent_message"]
            parsed["parent_text"] = SlackMessageParser.parse_message(parent)["text"]
            
        return parsed

    @staticmethod
    def parse_archive_url(url: str) -> Dict[str, Any]:
        """Parse a Slack archive URL and extract metadata"""
        # Example URL pattern:
        # https://openloophealth.slack.com/archives/C06PKHVCE67/p1731161693874449
        
        pattern = r'archives/([A-Z0-9]+)/p(\d+)'
        match = re.search(pattern, url)
        
        if not match:
            return {}
            
        channel_id, timestamp = match.groups()
        
        # Convert Slack timestamp format
        ts = timestamp[:10] + "." + timestamp[10:]
        
        return {
            "channel_id": channel_id,
            "timestamp": ts,
            "url": url
        }

def parse_slack_message(raw_message: Dict[str, Any]) -> Dict[str, Any]:
    """Main entry point for parsing Slack messages"""
    parser = SlackMessageParser()
    return parser.parse_message(raw_message)
