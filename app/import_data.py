import os
import re
import shutil
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
from pathlib import Path
import time
import json
from app.embeddings import EmbeddingService
import argparse
from bson import ObjectId

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
    # Parse message line format: [YYYY-MM-DD HH:MM:SS UTC] <username> message
    match = re.match(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)\] <([^>]+)> (.*)', line)
    if match:
        timestamp_str, username, text = match.groups()
        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S UTC')
        return {
            'ts': f"{timestamp.timestamp():.1f}",  # Format with one decimal place
            'timestamp': timestamp,
            'user': username,
            'text': text.strip()
        }
    
    # Handle file shares
    file_share = re.match(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)\] <([^>]+)> shared file\(s\) (.*)', line)
    if file_share:
        timestamp_str, username, file_info = file_share.groups()
        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S UTC')
        return {
            'ts': f"{timestamp.timestamp():.1f}",  # Format with one decimal place
            'timestamp': timestamp,
            'user': username,
            'type': 'file_share',
            'file_info': file_info.strip()
        }
    
    # Handle user joins
    join = re.match(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)\] (.*) joined the channel', line)
    if join:
        timestamp_str, username = join.groups()
        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S UTC')
        return {
            'ts': f"{timestamp.timestamp():.1f}",  # Format with one decimal place
            'timestamp': timestamp,
            'user': username,
            'type': 'join'
        }
    
    return None

async def parse_channel_metadata(lines):
    metadata = {}
    for line in lines:
        line = line.strip()
        if line.startswith('Channel Name:'):
            metadata['name'] = line.split(':', 1)[1].strip()
        elif line.startswith('Channel ID:'):
            metadata['id'] = line.split(':', 1)[1].strip()
        elif line.startswith('Created:'):
            created_str = line.split(':', 1)[1].strip()
            metadata['created'] = datetime.strptime(created_str.split(' UTC')[0], '%Y-%m-%d %H:%M:%S')
        elif line.startswith('Type:'):
            metadata['type'] = line.split(':', 1)[1].strip()
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
                await process_channel(db, channel_path, channel_dir)
    
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

async def process_channel(db, channel_path, channel_dir):
    channel_file = os.path.join(channel_path, f"{channel_dir}.txt")
    
    if os.path.exists(channel_file):
        try:
            message_count = 0
            channel_metadata = {}
            test_mode = os.getenv("TEST_MODE", "false").lower() == "true"
            
            async for item in parse_conversation_file(channel_file, 'channel'):
                if item.get('type') == 'metadata':
                    channel_metadata = item['data']
                    continue
                    
                # Format message
                message = {
                    'conversation_id': channel_dir,
                    'ts': item.get('ts'),
                    'text': item.get('text', ''),
                    'timestamp': item.get('timestamp'),
                    'user': item.get('user'),
                    'type': item.get('type', 'message')
                }
                
                try:
                    await db.messages.update_one(
                        {'ts': message['ts'], 'conversation_id': message['conversation_id']},
                        {'$set': message},
                        upsert=True
                    )
                    message_count += 1
                    if message_count % 100 == 0:
                        print(f"Processed {message_count} messages from {channel_dir}")
                    
                    if test_mode and message_count >= 1000:
                        print(f"Test mode: Reached 1000 messages, stopping import")
                        break
                        
                except Exception as e:
                    if not "duplicate key error" in str(e).lower():
                        print(f"Error inserting message in {channel_dir}: {str(e)}")
            
            # Update conversation
            metadata = {
                '_id': channel_dir,
                'name': channel_dir,  # Use directory name as display name
                'type': 'channel',
                'message_count': message_count
            }
            if channel_metadata:
                metadata.update(channel_metadata)
            
            await db.conversations.update_one(
                {'_id': metadata['_id']},
                {'$set': metadata},
                upsert=True
            )
            
            print(f"Completed processing {message_count} messages from {channel_dir}")
        except Exception as e:
            print(f"Error processing channel {channel_dir}: {e}")
            return

async def process_dm(db, dm_path, dm_dir):
    dm_file = os.path.join(dm_path, f"{dm_dir}.txt")
    
    if os.path.exists(dm_file):
        try:
            message_count = 0
            dm_metadata = {}
            
            async for item in parse_conversation_file(dm_file, 'dm'):
                if item.get('type') == 'metadata':
                    dm_metadata = item['data']
                    continue
                    
                # Format message
                message = {
                    'conversation_id': dm_dir,
                    'ts': item.get('ts'),
                    'text': item.get('text', ''),
                    'timestamp': item.get('timestamp'),
                    'user': item.get('user'),
                    'type': item.get('type', 'message')
                }
                
                try:
                    await db.messages.update_one(
                        {'ts': message['ts'], 'conversation_id': message['conversation_id']},
                        {'$set': message},
                        upsert=True
                    )
                    message_count += 1
                    if message_count % 100 == 0:
                        print(f"Processed {message_count} messages from {dm_dir}")
                except Exception as e:
                    if not "duplicate key error" in str(e).lower():
                        print(f"Error inserting message in {dm_dir}: {str(e)}")
            
            # Update conversation
            participants = dm_dir.split('-')
            metadata = {
                '_id': dm_dir,
                'name': ', '.join(participants),
                'type': 'dm',
                'participants': participants,
                'message_count': message_count
            }
            if dm_metadata:
                metadata.update(dm_metadata)
            
            await db.conversations.update_one(
                {'_id': metadata['_id']},
                {'$set': metadata},
                upsert=True
            )
            
            print(f"Completed processing {message_count} messages from {dm_dir}")
        except Exception as e:
            print(f"Error processing DM {dm_dir}: {str(e)}")

async def update_chroma_embeddings(db):
    # Generate and store embeddings for new messages
    new_messages_for_embedding = []
    async for msg in db.messages.find():
        new_messages_for_embedding.append(msg)
    if new_messages_for_embedding:
        await embedding_service.add_messages(new_messages_for_embedding)

async def import_slack_export(db: AsyncIOMotorClient, file_path: Path, upload_id: str):
    """Import a Slack export ZIP file"""
    try:
        print(f"Starting import of {file_path}")
        extract_dir = Path("/data/extracts") / file_path.stem
        
        # Extract the ZIP file
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)
        
        # Update status to extracting
        await db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {"$set": {
                "status": "extracting",
                "progress": "Extracting ZIP file...",
                "updated_at": datetime.utcnow()
            }}
        )
        
        print(f"Extracting to {extract_dir}")
        shutil.unpack_archive(file_path, extract_dir, 'zip')
        
        # Update status to importing channels
        await db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {"$set": {
                "status": "importing_channels",
                "progress": "Starting channel import...",
                "updated_at": datetime.utcnow()
            }}
        )
        
        # Process channels
        channels_dir = extract_dir / "channels"
        channel_count = 0
        message_count = 0
        
        if channels_dir.exists():
            channel_list = list(channels_dir.iterdir())
            total_channels = len([d for d in channel_list if d.is_dir()])
            
            for channel_dir in channel_list:
                if channel_dir.is_dir():
                    print(f"Processing channel: {channel_dir.name}")
                    
                    # Update progress
                    channel_count += 1
                    await db.uploads.update_one(
                        {"_id": ObjectId(upload_id)},
                        {"$set": {
                            "progress": f"Processing channel {channel_count}/{total_channels}: {channel_dir.name}",
                            "updated_at": datetime.utcnow()
                        }}
                    )
                    
                    # Process channel
                    channel_messages = await process_channel(db, channel_dir / "messages.json", channel_dir)
                    message_count += channel_messages
        
        # Process DMs
        dms_dir = extract_dir / "direct_messages"
        dm_count = 0
        
        if dms_dir.exists():
            dm_list = list(dms_dir.iterdir())
            total_dms = len([d for d in dm_list if d.is_dir()])
            
            for dm_dir in dm_list:
                if dm_dir.is_dir():
                    print(f"Processing DM: {dm_dir.name}")
                    
                    # Update progress
                    dm_count += 1
                    await db.uploads.update_one(
                        {"_id": ObjectId(upload_id)},
                        {"$set": {
                            "progress": f"Processing DM {dm_count}/{total_dms}: {dm_dir.name}",
                            "updated_at": datetime.utcnow()
                        }}
                    )
                    
                    # Process DM
                    dm_messages = await process_dm(db, dm_dir / "messages.json", dm_dir)
                    message_count += dm_messages
        
        # Update embeddings
        await db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {"$set": {
                "status": "generating_embeddings",
                "progress": "Generating embeddings...",
                "updated_at": datetime.utcnow()
            }}
        )
        
        await update_chroma_embeddings(db)
        
        # Mark as complete
        await db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {"$set": {
                "status": "complete",
                "progress": f"Imported {channel_count} channels and {dm_count} DMs with {message_count} total messages",
                "updated_at": datetime.utcnow()
            }}
        )
        
        print(f"Import complete: {channel_count} channels, {dm_count} DMs, {message_count} messages")
        
    except Exception as e:
        print(f"Import failed: {str(e)}")
        # Update status to error
        try:
            await db.uploads.update_one(
                {"_id": ObjectId(upload_id)},
                {"$set": {
                    "status": "error",
                    "error": str(e),
                    "updated_at": datetime.utcnow()
                }}
            )
        except Exception as e2:
            print(f"Failed to update error status: {str(e2)}")
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
            await process_channel(db, channel_path, channel_dir)
        except Exception as e:
            print(f"Error processing channel {channel_dir}: {e}")
            continue

    await update_chroma_embeddings(db)

if __name__ == "__main__":
    asyncio.run(main())
