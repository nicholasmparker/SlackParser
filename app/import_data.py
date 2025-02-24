import os
import re
import shutil
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
import time
import json
from app.embeddings import EmbeddingService
import argparse
from bson import ObjectId
import zipfile
import logging

logger = logging.getLogger(__name__)

# Constants
DATA_DIR = os.getenv("DATA_DIR", "data")
FILE_STORAGE = os.getenv("FILE_STORAGE", "file_storage")
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
EXPORT_DIR = os.getenv("EXPORT_DIR", "export")

# Initialize embedding service
embedding_service = EmbeddingService()

async def wait_for_mongodb():
    """Wait for MongoDB to be ready"""
    max_retries = 30
    retry_delay = 1
    
    for i in range(max_retries):
        try:
            print(f"Attempting to connect to MongoDB... ({i+1}/{max_retries})")
            client = AsyncIOMotorClient(MONGODB_URL)
            await client.admin.command('ping')
            print("Successfully connected to MongoDB")
            return client
        except Exception as e:
            print(f"Failed to connect to MongoDB: {str(e)}")
            if i == max_retries - 1:
                raise Exception(f"Failed to connect to MongoDB after {max_retries} attempts: {str(e)}")
            print(f"Waiting {retry_delay} seconds before next attempt...")
            await asyncio.sleep(retry_delay)

async def parse_message(line):
    """Parse a message line from the new Slack export format
    
    Format: [TIMESTAMP UTC] <USER> MESSAGE
    Example: [2023-07-06 22:51:43 UTC] <diane> Message text
    """
    try:
        # Extract timestamp
        timestamp_match = re.match(r'\[(.*?) UTC\]', line)
        if not timestamp_match:
            return None
        timestamp_str = timestamp_match.group(1)
        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
        ts = timestamp.timestamp()
        
        # Extract user and message
        remaining = line[line.index(']')+1:].strip()
        user_match = re.match(r'<(.+?)> (.*)', remaining)
        if not user_match:
            return None
        user = user_match.group(1)
        text = user_match.group(2)
        
        return {
            'ts': str(ts),
            'timestamp': timestamp,
            'user': user,
            'text': text,
            'type': 'message'
        }
    except Exception as e:
        print(f"Error parsing message line: {str(e)}")
        print(f"Line: {line}")
        return None

async def parse_channel_metadata(lines):
    """Parse channel metadata from the header lines"""
    metadata = {}
    for line in lines:
        line = line.strip()
        if line.startswith('Channel Name:'):
            metadata['name'] = line.split(':', 1)[1].strip().lstrip('#')
        elif line.startswith('Channel ID:'):
            metadata['id'] = line.split(':', 1)[1].strip()
        elif line.startswith('Created:'):
            created_str = line.split(':', 1)[1].strip()
            metadata['created'] = datetime.strptime(created_str.split(' UTC')[0], '%Y-%m-%d %H:%M:%S')
        elif line.startswith('Type:'):
            metadata['type'] = line.split(':', 1)[1].strip()
    return metadata

async def parse_dm_metadata(lines):
    """Parse DM metadata from the header lines
    
    Example format:
    Private conversation between casey, tj
    Channel ID: D05GCTX0678
    Created: 2023-07-11 21:17:07 UTC
    Type: Direct Message
    """
    metadata = {}
    for line in lines:
        line = line.strip()
        if line.startswith('Private conversation between'):
            users = line.split('between ', 1)[1].split(', ')
            metadata['name'] = '-'.join(users)
        elif line.startswith('Channel ID:'):
            metadata['id'] = line.split(':', 1)[1].strip()
        elif line.startswith('Created:'):
            created_str = line.split(':', 1)[1].strip()
            try:
                metadata['created'] = datetime.strptime(created_str.split(' UTC')[0], '%Y-%m-%d %H:%M:%S')
            except ValueError as e:
                print(f"Error parsing created date: {e}")
                print(f"Line was: {line}")
    metadata['type'] = 'dm'  # Always set type to dm
    return metadata

async def parse_conversation_file(file_path, conversation_type='channel'):
    """Parse a conversation file and yield messages one at a time"""
    metadata = {}
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                if line.startswith('['):
                    # This is a message
                    message = await parse_message(line)
                    if message:
                        message['conversation_type'] = conversation_type
                        yield message
                else:
                    # This might be metadata
                    if conversation_type == 'channel':
                        metadata.update(await parse_channel_metadata([line]))
    
    # Yield metadata as a special message type
    yield {'type': 'metadata', 'data': metadata}

async def import_slack_data():
    """Import Slack data from the mounted data directory"""
    print("Starting Slack data import...")
    
    # Wait for MongoDB to be ready
    client = await wait_for_mongodb()
    db = client.slack_data
    
    # Clear existing collections to avoid duplicate key errors
    print("Clearing existing collections...")
    await db.messages.delete_many({})
    await db.conversations.delete_many({})
    await db.files.delete_many({})
    await db.canvases.delete_many({})
    
    # Create indexes
    print("Creating indexes...")
    await db.messages.create_index([("text", "text")])
    await db.messages.create_index([("conversation_id", 1)])
    await db.messages.create_index([("timestamp", 1)])
    await db.messages.create_index([("conversation_type", 1)])
    await db.messages.create_index([("ts", 1)], unique=True)
    await db.conversations.create_index([("type", 1)])
    await db.files.create_index([("name", 1)])
    await db.files.create_index([("path", 1)], unique=True)
    
    # Import conversations first
    print("\nImporting conversations...")
    await import_conversations()
    
    # Process channels
    print("\nProcessing Channels...")
    channels_dir = os.path.join(DATA_DIR, "channels")
    if os.path.exists(channels_dir):
        for channel_dir in os.listdir(channels_dir):
            channel_path = os.path.join(channels_dir, channel_dir)
            if os.path.isdir(channel_path):
                print(f"Processing channel: {channel_dir}")
                channel_file = os.path.join(channel_path, f"{channel_dir}.txt")
                await process_channel(db, channel_file, channel_dir)
    
    # Create .import_complete file to indicate successful import
    with open("/data/.import_complete", "w") as f:
        f.write(str(datetime.now()))
    
    print("\nImport completed successfully!")

async def import_new_messages() -> int:
    """Import only new messages from the Slack data directory.
    Returns the number of new messages imported."""
    
    # Wait for MongoDB to be ready
    client = await wait_for_mongodb()
    db = client.slack_data
    
    # Get the timestamp of the most recent message
    latest_msg = await db.messages.find_one(
        sort=[("ts", -1)]
    )
    latest_ts = latest_msg["ts"] if latest_msg else 0
    
    # Track number of new messages
    new_message_count = 0
    new_messages_for_embedding = []
    
    # Import all conversations first
    conversations = await import_conversations()
    
    # For each conversation, import messages newer than latest_ts
    for conv in conversations:
        conv_path = os.path.join(DATA_DIR, conv["id"])
        if not os.path.isdir(conv_path):
            continue
            
        # Process each JSON file in conversation directory
        for json_file in sorted(os.listdir(conv_path)):
            if not json_file.endswith(".json"):
                continue
                
            with open(os.path.join(conv_path, json_file)) as f:
                messages = json.load(f)
                
            # Filter and import only new messages
            new_messages = [msg for msg in messages if float(msg["ts"]) > latest_ts]
            if new_messages:
                # Add conversation_id to messages
                for msg in new_messages:
                    msg["conversation_id"] = conv["id"]
                
                # Insert into MongoDB
                result = await db.messages.insert_many(new_messages)
                
                # Prepare messages for embedding
                messages_with_ids = []
                for msg, inserted_id in zip(new_messages, result.inserted_ids):
                    msg["_id"] = inserted_id
                    messages_with_ids.append(msg)
                new_messages_for_embedding.extend(messages_with_ids)
                
                new_message_count += len(new_messages)
    
    # Generate and store embeddings for new messages
    if new_messages_for_embedding:
        await embedding_service.add_messages(new_messages_for_embedding)
    
    return new_message_count

async def import_conversations():
    """Import all conversations from the Slack data directory."""
    client = await wait_for_mongodb()
    db = client.slack_data
    
    conversations = []
    
    # Import channels
    channels_dir = os.path.join(DATA_DIR, "channels")
    if os.path.exists(channels_dir):
        for channel in os.listdir(channels_dir):
            channel_path = os.path.join(channels_dir, channel)
            if os.path.isdir(channel_path):
                # For channels, use the directory name as both ID and name
                metadata = {
                    '_id': channel,
                    'name': channel,
                    'type': 'channel'
                }
                conversations.append(metadata)
                
                # Upsert to database
                await db.conversations.update_one(
                    {"_id": metadata['_id']},
                    {"$set": metadata},
                    upsert=True
                )
    
    # Import DMs
    dms_dir = os.path.join(DATA_DIR, "dms")
    if os.path.exists(dms_dir):
        for dm in os.listdir(dms_dir):
            dm_path = os.path.join(dms_dir, dm)
            if os.path.isdir(dm_path):
                # For DMs, use the directory name as ID and format participants for display
                participants = dm.split('-')
                metadata = {
                    '_id': dm,
                    'name': ', '.join(participants),
                    'type': 'dm',
                    'participants': participants
                }
                conversations.append(metadata)
                
                # Upsert to database
                await db.conversations.update_one(
                    {"_id": metadata['_id']},
                    {"$set": metadata},
                    upsert=True
                )
    
    return conversations

async def insert_messages(db: Any, messages: List[Dict[str, Any]], batch_size=50):
    """Insert messages into MongoDB in batches"""
    try:
        for i in range(0, len(messages), batch_size):
            batch = messages[i:i + batch_size]
            try:
                await db.messages.insert_many(batch)
            except Exception as e:
                print(f"Error inserting batch: {str(e)}")
                # If it's a duplicate key error, try inserting one at a time
                if "duplicate key error" in str(e):
                    print("Attempting to insert messages one at a time...")
                    for msg in batch:
                        try:
                            await db.messages.insert_one(msg)
                        except Exception as e:
                            if "duplicate key error" not in str(e):
                                print(f"Error inserting message: {str(e)}")
                else:
                    raise
    except Exception as e:
        print(f"Error in insert_messages: {str(e)}")
        raise

async def process_channel(db: Any, channel_path: Path, channel_dir: str):
    """Process a channel directory and import its messages"""
    try:
        channel_name = channel_dir
        print(f"\nProcessing channel: {channel_name}")
        
        # Look for channel_name.txt in the channel directory
        messages_file = channel_path / f"{channel_name}.txt"
        print(f"Looking for messages file at: {messages_file}")
        
        if not messages_file.exists():
            print(f"No {channel_name}.txt found in {channel_name}, skipping")
            return 0
            
        messages = []
        in_messages_section = False
        metadata_lines = []
        
        print(f"Reading file: {messages_file}")
        with open(messages_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                # Collect metadata lines until we hit the Messages section
                if line == "Messages:":
                    in_messages_section = True
                    print("Found Messages section, parsing metadata:", metadata_lines)
                    # Parse and store channel metadata
                    metadata = await parse_channel_metadata(metadata_lines)
                    metadata['_id'] = channel_name  # Use channel name as ID for now
                    metadata['type'] = 'channel'
                    print(f"Channel metadata: {metadata}")
                    
                    # Upsert channel metadata to conversations collection
                    await db.conversations.update_one(
                        {"_id": metadata['_id']},
                        {"$set": metadata},
                        upsert=True
                    )
                    print(f"Stored channel metadata for {channel_name}")
                    continue
                
                if not in_messages_section:
                    metadata_lines.append(line)
                    continue
                
                # Skip date headers (lines starting with ---)
                if line.startswith('---'):
                    continue
                
                # Parse message
                message = await parse_message(line)
                if message:
                    message['conversation_id'] = channel_name
                    message['conversation_type'] = 'channel'
                    messages.append(message)
                    
        if messages:
            print(f"INFO: Processing {len(messages)} messages in batches of 50")
            await insert_messages(db, messages)
            return len(messages)
        return 0
            
    except Exception as e:
        print(f"Error processing channel {channel_dir}: {str(e)}")
        import traceback
        traceback.print_exc()
        return 0

async def process_dm(db: Any, dm_path: Path, dm_dir: str):
    """Process a DM directory and import its messages
    
    Args:
        db: MongoDB database connection
        dm_path: Path to the DM's directory
        dm_dir: Name of the DM directory
    """
    try:
        print(f"\nProcessing DM: {dm_dir}")
        messages_file = dm_path / f"{dm_dir}.txt"
        
        if not messages_file.exists():
            print(f"No messages file found at {messages_file}")
            return 0
            
        messages = []
        metadata_lines = []
        in_messages_section = False
        
        with open(messages_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                    
                if line == "Messages:":
                    in_messages_section = True
                    metadata = await parse_dm_metadata(metadata_lines)
                    metadata['_id'] = dm_dir
                    print(f"Parsed DM metadata: {metadata}")
                    
                    await db.conversations.update_one(
                        {"_id": metadata['_id']},
                        {"$set": metadata},
                        upsert=True
                    )
                    continue
                    
                if not in_messages_section:
                    metadata_lines.append(line)
                    continue
                    
                if line.startswith('---'):
                    continue
                    
                message = await parse_message(line)
                if message:
                    message['conversation_id'] = dm_dir
                    message['conversation_type'] = 'dm'
                    messages.append(message)
                    
        if messages:
            print(f"Inserting {len(messages)} messages from DM {dm_dir}")
            await insert_messages(db, messages)
            return len(messages)
        return 0
            
    except Exception as e:
        print(f"Error processing DM {dm_dir}: {str(e)}")
        traceback.print_exc()
        return 0

async def update_chroma_embeddings(db):
    # Generate and store embeddings for new messages
    new_messages_for_embedding = []
    async for msg in db.messages.find():
        new_messages_for_embedding.append(msg)
    if new_messages_for_embedding:
        await embedding_service.add_messages(new_messages_for_embedding)

async def import_slack_export(db: Any, file_path: Path, upload_id: str):
    """Import a Slack export ZIP file
    
    Args:
        db: MongoDB database connection
        file_path: Path to the ZIP file
        upload_id: ID of the upload record
    """
    try:
        # Set up extract directory
        extract_dir = Path('/data/extracted') / upload_id
        
        # Check if files are already extracted
        slack_export_dir = None
        if extract_dir.exists():
            # Look for existing slack-export directory
            for item in extract_dir.iterdir():
                if item.is_dir() and ('slack-export' in item.name):
                    slack_export_dir = item
                    print(f"Using existing extracted files in {slack_export_dir}")
                    break
        
        # Only extract if needed
        if not slack_export_dir:
            print(f"No extracted files found, extracting ZIP file to {extract_dir}")
            await extract_with_progress(db, str(file_path), extract_dir, upload_id)
            
            # Find the slack-export directory after extraction
            for item in extract_dir.iterdir():
                if item.is_dir() and ('slack-export' in item.name):
                    slack_export_dir = item
                    break
                    
        if not slack_export_dir:
            raise Exception("Could not find slack-export directory in ZIP file")
            
        # Process channels
        channels_dir = slack_export_dir / 'channels'
        if channels_dir.exists():
            # Update status
            await db.uploads.update_one(
                {"_id": ObjectId(upload_id)},
                {"$set": {"status": "IMPORTING", "progress": "Processing channels..."}}
            )
            
            # Process each channel
            total_messages = 0
            for channel_dir in channels_dir.iterdir():
                if channel_dir.is_dir():
                    messages = await process_channel(db, channel_dir, channel_dir.name)
                    total_messages += messages
                    
                    # Update progress
                    await db.uploads.update_one(
                        {"_id": ObjectId(upload_id)},
                        {"$set": {"progress": f"Imported {total_messages} messages..."}}
                    )
        else:
            print("No channels directory found")
            total_messages = 0
        
        # Process DMs
        print("\nProcessing DMs...")
        dms_dir = slack_export_dir / 'dms'
        print(f"Looking for DMs directory at {dms_dir}")
        if dms_dir.exists():
            print(f"Found DMs directory at {dms_dir}")
            for dm_dir in dms_dir.iterdir():
                if dm_dir.is_dir():
                    print(f"Found DM directory: {dm_dir}")
                    dm_count = await process_dm(db, dm_dir, dm_dir.name)
                    total_messages += dm_count
                    print(f"Processed {dm_count} messages from DM {dm_dir.name}")
        else:
            print("No DMs directory found")
        
        # Mark as complete
        await db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {
                "$set": {
                    "status": "complete",
                    "progress": f"Imported {total_messages} messages"
                }
            }
        )
        
    except Exception as e:
        print(f"Error importing Slack export: {str(e)}")
        import traceback
        traceback.print_exc()
        await db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {
                "$set": {
                    "status": "error",
                    "error": str(e)
                }
            }
        )

def get_zip_total_size(zip_path: str) -> int:
    """Get the total uncompressed size of all files in the ZIP"""
    total = 0
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        for info in zip_ref.infolist():
            total += info.file_size
    return total

async def extract_with_progress(db: Any, zip_path: str, extract_dir: Path, upload_id: str):
    """Extract ZIP file with progress updates"""
    try:
        total_size = get_zip_total_size(zip_path)  
        extracted_size = 0
        last_update_time = time.time()
        UPDATE_INTERVAL = 1.0  # Update progress at most once per second
        
        print(f"Extracting ZIP file: {zip_path}")
        print(f"Total uncompressed size: {total_size:,} bytes")
        print(f"Extracting to: {extract_dir}")
        
        # Extract all files at once for better performance
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # Get list of all files (not directories)
            files_to_extract = [f for f in zip_ref.infolist() if not f.is_dir()]
            
            # Extract files in batches
            BATCH_SIZE = 100
            for i in range(0, len(files_to_extract), BATCH_SIZE):
                batch = files_to_extract[i:i + BATCH_SIZE]
                
                # Extract batch
                for file_info in batch:
                    zip_ref.extract(file_info, extract_dir)
                    extracted_size += file_info.file_size
                
                # Update progress at most once per second
                current_time = time.time()
                if current_time - last_update_time >= UPDATE_INTERVAL:
                    progress_percent = int((extracted_size / total_size) * 100) if total_size > 0 else 0
                    await db.uploads.update_one(
                        {"_id": ObjectId(upload_id)},
                        {"$set": {
                            "status": "extracting",  
                            "progress": f"Extracted {extracted_size:,} of {total_size:,} bytes ({progress_percent}%)",
                            "progress_percent": progress_percent,
                            "updated_at": datetime.utcnow()
                        }}
                    )
                    last_update_time = current_time
        
        # Final progress update
        await db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {"$set": {
                "status": "extracting",  
                "progress": f"Extracted {extracted_size:,} of {total_size:,} bytes (100%)",
                "progress_percent": 100,
                "updated_at": datetime.utcnow()
            }}
        )
        
        print(f"Extraction complete. Listing contents of {extract_dir}:")
        for root, dirs, files in os.walk(extract_dir):
            print(f"\nDirectory: {root}")
            for d in dirs:
                print(f"  Dir: {d}")
            for f in files:
                print(f"  File: {f}")
                
    except Exception as e:
        print(f"Error during extraction: {str(e)}")
        raise

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data_dir', type=str, default='/data')
    parser.add_argument('--start_idx', type=int, default=0, help='Start index for channel range')
    parser.add_argument('--end_idx', type=int, default=None, help='End index for channel range')
    args = parser.parse_args()

    mongo_client = AsyncIOMotorClient('mongodb://mongodb:27017')
    db = mongo_client.slack_data
    
    # Get sorted list of channel directories
    channel_dirs = sorted([
        d for d in os.listdir(os.path.join(args.data_dir, 'channels'))
        if os.path.isdir(os.path.join(args.data_dir, 'channels', d))
    ])

    # Apply range if specified
    if args.end_idx is not None:
        channel_dirs = channel_dirs[args.start_idx:args.end_idx]
    else:
        channel_dirs = channel_dirs[args.start_idx:]

    print(f"Importing channels {args.start_idx} to {args.end_idx if args.end_idx else 'end'}")
    print(f"Channel list: {', '.join(channel_dirs)}")

    # Process each channel directory
    for channel_dir in channel_dirs:
        channel_path = os.path.join(args.data_dir, 'channels', channel_dir)
        print(f"\nProcessing channel: {channel_dir}")
        
        try:
            await process_channel(db, os.path.join(channel_path, f"{channel_dir}.txt"), channel_dir)
        except Exception as e:
            print(f"Error processing channel {channel_dir}: {e}")
            continue

    await update_chroma_embeddings(db)

if __name__ == "__main__":
    asyncio.run(main())
