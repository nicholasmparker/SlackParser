from pymongo.database import Database
from fastapi import FastAPI, Request, Query, HTTPException, Body, File, UploadFile
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional, Dict, Any, List, Union
import os
import json
import logging
import asyncio
import tempfile
import zipfile
import shutil
from datetime import datetime
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import status
from werkzeug.utils import secure_filename
import traceback
from pathlib import Path
from pydantic import BaseModel
from app.embeddings import EmbeddingService
from app.db.models import Channel, Message, Upload, FailedImport
from app.importer.importer import process_file, import_slack_export
from app.importer.parser import parse_message, parse_channel_metadata, parse_dm_metadata, ParserError
import glob
import aiohttp

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Get environment variables
FILE_STORAGE = os.getenv("FILE_STORAGE", "file_storage")
MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
MONGO_DB = os.getenv("MONGO_DB", "slack_data")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:8000")
DATA_DIR = os.getenv("DATA_DIR", "data")

# Get base directory
BASE_DIR = Path(__file__).resolve().parent

# Setup static files and templates
static_dir = BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
app.mount("/files", StaticFiles(directory=FILE_STORAGE, html=True), name="files")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Upload directory from environment
UPLOAD_DIR = Path(DATA_DIR) / "uploads"

# Add template filters
def timedelta_filter(value):
    """Format a timestamp as a human-readable time delta"""
    if not value:
        return ""

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            value = float(value)
            dt = datetime.fromtimestamp(value)
        except ValueError:
            return value
    else:
        try:
            dt = datetime.fromtimestamp(value)
        except (TypeError, ValueError):
            return str(value)

    return dt.strftime("%B %d, %Y")

def from_json_filter(value):
    """Parse a JSON string into a Python object"""
    if not value:
        return None
    try:
        return json.loads(value)
    except:
        return None

def strftime_filter(value, fmt="%Y-%m-%d %H:%M:%S"):
    """Format a date according to the given format.

    For messages, we follow Slack's display logic:
    - Messages from today: show only time (3:56 PM)
    - Messages from this week: show day and time (Wed 3:56 PM)
    - Older messages: show date and time (Feb 24, 3:56 PM)
    """
    if not value:
        return ""

    try:
        # Convert timestamp to datetime if needed
        if isinstance(value, str):
            # Try parsing as float first (Unix timestamp)
            try:
                value = float(value)
            except ValueError:
                # If not a float, try parsing as datetime string
                try:
                    value = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    return value

        if isinstance(value, (int, float)):
            value = datetime.fromtimestamp(float(value))

        if not isinstance(value, datetime):
            return str(value)

        now = datetime.now()

        # Messages from today
        if value.date() == now.date():
            return value.strftime("%I:%M %p").lstrip("0")

        # Messages from this week
        elif (now - value).days < 7:
            return value.strftime("%a %I:%M %p").lstrip("0")

        # Older messages
        else:
            return value.strftime("%b %d, %I:%M %p").lstrip("0")

    except Exception as e:
        print(f"Error formatting timestamp: {str(e)}")
        return str(value)

templates.env.filters["timedelta"] = timedelta_filter
templates.env.filters["from_json"] = from_json_filter
templates.env.filters["strftime"] = strftime_filter

# Initialize embeddings service
app.embeddings = EmbeddingService()

# MongoDB connection
@app.on_event("startup")
def startup_db_client():
    try:
        # Initialize MongoDB client
        app.mongodb_client = AsyncIOMotorClient(MONGO_URL)
        app.db = app.mongodb_client[MONGO_DB]
        logger.info(f"Connected to MongoDB at {MONGO_URL}")

        # Initialize ChromaDB client
        app.embeddings.initialize()

        # Create indexes
        asyncio.create_task(setup_indexes())

    except Exception as e:
        logger.error(f"Error during startup: {str(e)}")
        raise e

@app.on_event("shutdown")
async def shutdown_db_client():
    """Close MongoDB connection on shutdown"""
    if hasattr(app, "mongodb_client"):
        app.mongodb_client.close()
        logger.info("Closed MongoDB connection")

# Ensure text search index exists
async def setup_indexes():
    """Create necessary database indexes"""
    try:
        # Create text index on messages collection
        await app.db.messages.create_index([("text", "text")])
        # Create index on conversation_id for faster lookups
        await app.db.messages.create_index("conversation_id")
        # Create index on ts for sorting
        await app.db.messages.create_index("ts")
        print("Created database indexes")
    except Exception as e:
        print(f"Error creating indexes: {e}")

def get_zip_total_size(zip_path: str) -> int:
    """Get the total uncompressed size of all files in the ZIP"""
    print(f"Calculating total size of {zip_path}")
    total = 0
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        for info in zip_ref.infolist():
            total += info.file_size
    print(f"Total size: {total} bytes")
    return total

async def extract_with_progress(db: Any, zip_path: str, extract_dir: Path, upload_id: ObjectId):
    """Extract ZIP file with progress updates"""
    print(f"Starting extraction with progress from {zip_path} to {extract_dir}")
    total_size = get_zip_total_size(zip_path)
    extracted_size = 0

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        for file_info in zip_ref.infolist():
            print(f"Extracting {file_info.filename}")
            zip_ref.extract(file_info, extract_dir)
            extracted_size += file_info.file_size
            percent = int((extracted_size / total_size) * 100)

            # Update progress every 5%
            if percent % 5 == 0:
                print(f"Progress: {percent}%")
                await db.uploads.update_one(
                    {"_id": upload_id},
                    {"$set": {
                        "status": "EXTRACTING",
                        "progress": f"Extracting ZIP file... {percent}% complete",
                        "progress_percent": percent,
                        "updated_at": datetime.utcnow()
                    }}
                )
    print("Extraction complete")

    # Update status to EXTRACTED when complete
    await db.uploads.update_one(
        {"_id": upload_id},
        {"$set": {
            "status": "EXTRACTED",
            "progress": "Extraction complete",
            "progress_percent": 100,
            "updated_at": datetime.utcnow()
        }}
    )

@app.get("/")
async def home(request: Request):
    """Render the home page with stats about the Slack workspace"""
    try:
        # Get system stats
        stats = await get_system_stats()

        # Render template with stats
        return templates.TemplateResponse(
            "home.html",
            {
                "request": request,
                "stats": stats
            }
        )
    except Exception as e:
        logger.error(f"Error loading home page: {str(e)}")
        return templates.TemplateResponse(
            "home.html",
            {
                "request": request,
                "stats": None
            }
        )

@app.get("/conversation/{conversation_id}")
async def view_conversation(
    request: Request,
    conversation_id: str,
    page: int = Query(1, ge=1),
    q: Optional[str] = None,
    ts: Optional[float] = None
):
    page_size = 50

    # Get conversation metadata with display name
    conversation = None
    try:
        # First try to parse as ObjectId
        object_id = ObjectId(conversation_id)
        conversation = await app.db.conversations.find_one({"_id": object_id})
    except (InvalidId, TypeError):
        # If not a valid ObjectId, try finding by channel_id
        logging.debug(f"Conversation ID {conversation_id} is not a valid ObjectId")

    if not conversation:
        # Try finding by channel_id
        conversation = await app.db.conversations.find_one({"channel_id": conversation_id})

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Use channel_id for querying messages
    channel_id = conversation.get("channel_id", str(conversation["_id"]))

    # Add display name
    if conversation.get("type") == "dm":
        name = conversation.get("name", str(conversation["_id"]))
        parts = name.split("-")
        display_name = ", ".join(parts)
    else:
        display_name = f"#{conversation.get('name', str(conversation['_id']))}"

    conversation["display_name"] = display_name

    # Build query
    query = {"conversation_id": channel_id}
    if q:
        query["$text"] = {"$search": q}

    # If we have a timestamp in the URL, find which page it's on
    if ts is not None:
        # Convert float timestamp to integer for matching
        ts_int = int(ts)
        # Count messages before this timestamp
        count_before = await app.db.messages.count_documents({
            **query,
            "ts": {"$gte": ts_int}  # Count messages after this one since we sort descending
        })
        # Calculate which page this message is on
        page = (count_before // page_size) + 1

    skip = (page - 1) * page_size

    # Get messages with sorting
    sort = [("timestamp", -1)]
    if q:  # If searching, also sort by text score
        sort.insert(0, ("score", {"$meta": "textScore"}))

    # Get messages and join with users collection
    pipeline = [
        {"$match": query},
        {"$sort": {"timestamp": -1}},
        {"$skip": skip},
        {"$limit": page_size},
        # Join with users collection
        {"$lookup": {
            "from": "users",
            "localField": "user",
            "foreignField": "_id",
            "as": "user_info"
        }},
        # Add user_name field if not present
        {"$addFields": {
            "user_name": {
                "$ifNull": [
                    # Try username from message
                    "$username",
                    # Try user_name from message
                    "$user_name",
                    # Try user info lookup
                    {"$arrayElemAt": ["$user_info.name", 0]},
                    # Fallback to user ID prefix
                    {
                        "$cond": {
                            "if": {"$regexMatch": {"input": "$user", "regex": "^U\\d+"}},
                            "then": {"$substrCP": ["$user", 0, 2]},
                            "else": "$user"
                        }
                    }
                ]
            }
        }},
        # Remove user_info array
        {"$project": {
            "user_info": 0
        }}
    ]

    messages = await app.db.messages.aggregate(pipeline).to_list(length=page_size)

    # Get total count for pagination
    total_messages = await app.db.messages.count_documents(query)
    total_pages = (total_messages + page_size - 1) // page_size

    return templates.TemplateResponse(
        "conversation.html",
        {
            "request": request,
            "conversation": conversation,
            "messages": messages,
            "page": page,
            "total_pages": total_pages,
            "q": q
        }
    )

@app.get("/conversations", response_class=HTMLResponse)
async def conversations(
    request: Request,
    page: int = Query(1, ge=1),
    q: str = "",
    type: str = "all"
):
    page_size = 20
    skip = (page - 1) * page_size

    # Build query
    query = {}
    if q:
        query["name"] = {"$regex": q, "$options": "i"}
    if type != "all":
        query["type"] = type

    # Get conversations with users for DMs
    pipeline = [
        {"$match": query},
        {"$project": {
            "_id": 1,
            "name": {"$ifNull": ["$name", "$_id"]},  # Use _id as fallback if name is null
            "type": 1,
            "channel_id": 1,  # Include channel_id for message lookup
            "display_name": {
                "$cond": {
                    "if": {"$eq": ["$type", "dm"]},
                    "then": {
                        "$reduce": {
                            "input": {"$split": [{"$ifNull": ["$name", "$_id"]}, "-"]},
                            "initialValue": "",
                            "in": {
                                "$cond": {
                                    "if": {"$eq": ["$$value", ""]},
                                    "then": "$$this",
                                    "else": {"$concat": ["$$value", ", ", "$$this"]}
                                }
                            }
                        }
                    },
                    "else": {"$concat": ["#", {"$ifNull": ["$name", "$_id"]}]}
                }
            }
        }},
        {"$sort": {"name": 1}},
        {"$skip": skip},
        {"$limit": page_size}
    ]
    conversations = await app.db.conversations.aggregate(pipeline).to_list(page_size)

    # Get message counts in bulk
    channel_ids = [c.get("channel_id", str(c["_id"])) for c in conversations]
    message_counts = await app.db.messages.aggregate([
        {"$match": {"conversation_id": {"$in": channel_ids}}},
        {"$group": {
            "_id": "$conversation_id",
            "count": {"$sum": 1},
            "latest_ts": {"$max": "$ts"},
            "latest_text": {"$last": "$text"},
            "latest_user": {"$last": "$user"}
        }}
    ]).to_list(None)

    # Convert to dict for O(1) lookup
    message_data = {str(m["_id"]): m for m in message_counts}

    # Merge data
    for conv in conversations:
        conv_id = str(conv.get("channel_id", conv["_id"]))
        if conv_id in message_data:
            data = message_data[conv_id]
            conv["message_count"] = data["count"]
            conv["latest_message"] = {
                "ts": data["latest_ts"],
                "text": data["latest_text"],
                "user": data["latest_user"]
            }
        else:
            conv["message_count"] = 0
            conv["latest_message"] = None

    # Get total count for pagination
    total = await app.db.conversations.count_documents(query)
    total_pages = (total + page_size - 1) // page_size

    return templates.TemplateResponse(
        "conversations.html",
        {
            "request": request,
            "conversations": conversations,
            "page": page,
            "total_pages": total_pages,
            "q": q,
            "type": type
        }
    )

@app.get("/files", response_class=HTMLResponse)
async def files(request: Request, q: str = ""):
    # Build query
    query = {}
    if q:
        query["name"] = {"$regex": q, "$options": "i"}

    # Get files matching query
    files = await app.db.files.find(query).sort("name", 1).to_list(length=None)

    return templates.TemplateResponse("files.html", {
        "request": request,
        "files": files,
        "query": q
    })

@app.get("/search")
async def search_page(request: Request, q: str = "", hybrid_alpha: float = 0.5):
    results = []
    if q:
        try:
            # Initialize embeddings service if not already initialized
            if not app.embeddings:
                app.embeddings = EmbeddingService()
                app.embeddings.initialize()

            # Perform semantic search
            search_results = await app.embeddings.search(
                query=q,
                limit=50,
                hybrid_alpha=hybrid_alpha
            )

            # Extract conversation IDs from results
            conversation_ids = list(set(r["metadata"]["conversation_id"] for r in search_results))

            # Get conversation details
            conversations = await app.db.conversations.find(
                {"_id": {"$in": conversation_ids}},
                {"name": 1, "type": 1}
            ).to_list(None)
            conv_map = {str(c["_id"]): c for c in conversations}

            # Format results for template
            results = []
            for r in search_results:
                try:
                    ts = float(r["metadata"]["timestamp"]) if r["metadata"]["timestamp"] and r["metadata"]["timestamp"].replace('.','').isdigit() else 0
                except (ValueError, TypeError):
                    ts = 0
                    logger.warning(f"Could not parse timestamp: {r['metadata']['timestamp']}")

                results.append({
                    "text": r["text"],
                    "conversation": conv_map.get(str(r["metadata"]["conversation_id"]), {"name": "Unknown", "type": "unknown"}),
                    "conversation_id": r["metadata"]["conversation_id"],
                    "user": r["metadata"]["user"],
                    "ts": ts,
                    "score": r["similarity"],
                    "keyword_match": r.get("keyword_match", False)
                })

            # Sort results by score
            results.sort(key=lambda x: x["score"], reverse=True)
        except Exception as e:
            logger.error(f"Error in search_page: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "query": q,
            "hybrid_alpha": hybrid_alpha,
            "results": results
        }
    )

@app.post("/search")
async def semantic_search(
    query: str = Body(..., embed=True),
    limit: int = Body(10),
    hybrid_alpha: float = Body(0.5),
    filter_channels: Optional[List[str]] = Body(None),
    filter_users: Optional[List[str]] = Body(None),
    filter_has_files: Optional[bool] = Body(None),
    filter_has_reactions: Optional[bool] = Body(None),
    filter_in_thread: Optional[bool] = Body(None),
    filter_date_range: Optional[tuple[datetime, datetime]] = Body(None)
):
    """Search for messages using hybrid search"""
    logger = logging.getLogger(__name__)
    try:
        logger.info(f"Searching with query: {query}")

        # Perform hybrid search
        results = await app.embeddings.search(
            query=query,
            limit=limit,
            hybrid_alpha=hybrid_alpha,
            filter_channels=filter_channels,
            filter_users=filter_users,
            filter_has_files=filter_has_files,
            filter_has_reactions=filter_has_reactions,
            filter_in_thread=filter_in_thread,
            filter_date_range=filter_date_range
        )

        # Get conversation details for each result
        for result in results:
            conversation = await app.db.conversations.find_one({"_id": result["conversation_id"]})
            result["conversation"] = conversation

        return {"results": results}

    except Exception as e:
        logger.error(f"Search error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin")
async def admin_page(request: Request):
    """Admin dashboard"""
    stats = await get_system_stats()

    # Get recent uploads
    uploads = []
    async for upload in app.db.uploads.find().sort("created_at", -1):
        # Convert ObjectId to string
        upload["_id"] = str(upload["_id"])

        # Ensure required fields exist
        if "size" not in upload:
            upload["size"] = 0
        if "status" not in upload:
            upload["status"] = "unknown"
        if "filename" not in upload:
            upload["filename"] = "unknown"
        if "created_at" not in upload:
            upload["created_at"] = datetime.now()
        if "progress" not in upload:
            upload["progress"] = None
        if "progress_percent" not in upload:
            upload["progress_percent"] = 0
        if "error" not in upload:
            upload["error"] = None

        # Debug logging
        print(f"Upload: {upload}")
        uploads.append(upload)

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "stats": stats,
            "uploads": uploads
        }
    )

@app.post("/admin/import/{upload_id}/start")
async def start_import(upload_id: str, request: Request):
    """Start the import process for an upload."""
    print(f"=== START IMPORT CALLED FOR {upload_id} ===")

    # Get database
    db = request.app.db

    # Convert upload_id to ObjectId
    upload_id_obj = ObjectId(upload_id)

    # Get upload - handle both async and sync MongoDB clients
    is_sync_client = str(type(db)) == "<class 'pymongo.database.Database'>"

    try:
        if is_sync_client:  # Sync client
            print("Using synchronous MongoDB client")
            upload = db.uploads.find_one({"_id": upload_id_obj})
        else:  # Async client
            print("Using asynchronous MongoDB client")
            upload = await db.uploads.find_one({"_id": upload_id_obj})

        if not upload:
            print(f"Upload not found: {upload_id}")
            return {"status": "error", "message": "Upload not found"}

        print(f"Found upload: {upload}")

        # Check current status
        current_status = upload.get("status", "UNKNOWN")
        print(f"Current status: {current_status}")

        if current_status == "EXTRACTED":
            print("Starting import phase")

            # Set extract path
            extract_path = Path("/data/extracts") / upload_id
            print(f"Extract path: {extract_path}")

            # Find the actual Slack export directory (it's usually a subdirectory)
            slack_export_dirs = list(extract_path.glob("slack-export*"))
            if slack_export_dirs:
                extract_path = slack_export_dirs[0]
                print(f"Found Slack export directory: {extract_path}")

            if not is_sync_client:  # Async client
                # Use async version
                asyncio.create_task(import_slack_export(db, extract_path, upload_id_obj))
            else:  # Sync client
                # Use sync version
                thread = threading.Thread(
                    target=import_slack_export_sync,
                    args=(db, extract_path, upload_id)
                )
                thread.daemon = True
                thread.start()
                print(f"Started import thread: {thread.name}")

            print("=== Started import phase successfully ===\n")
            return {"status": "success", "message": "Import started"}

        elif current_status == "UPLOADED":
            print("Starting extraction phase")

            # Start extraction in a separate thread
            file_path = upload.get("file_path", "")
            extract_path = Path("/data/extracts") / upload_id

            if not is_sync_client:  # Async client
                # Use async version
                asyncio.create_task(extract_with_progress(db, file_path, extract_path, upload_id_obj))
            else:  # Sync client
                # Use sync version
                thread = threading.Thread(
                    target=extract_with_progress_sync,
                    args=(db, file_path, extract_path, upload_id)
                )
                thread.daemon = True
                thread.start()
                print(f"Started extraction thread: {thread.name}")

            print("=== Started extraction phase successfully ===\n")
            return {"status": "success", "message": "Extraction started"}

        else:
            print(f"=== Started {current_status} phase successfully ===\n")
            return {"status": "success", "message": f"{current_status} started"}

    except Exception as e:
        print(f"Error in start_import: {e}")
        print(f"Error type: {type(e)}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}

@app.get("/admin/import-status/{upload_id}")
async def get_single_import_status(upload_id: str):
    """Get the status of a specific import"""
    try:
        # Convert the upload_id string to ObjectId
        upload_oid = ObjectId(upload_id)

        # Find the upload in the database
        upload = await app.db.uploads.find_one({"_id": upload_oid})

        if not upload:
            return JSONResponse(
                status_code=404,
                content={"error": "Upload not found"}
            )

        # Convert ObjectId to string for JSON serialization
        upload["_id"] = str(upload["_id"])

        # Convert datetime objects to ISO format strings
        for key, value in upload.items():
            if isinstance(value, datetime):
                upload[key] = value.isoformat()

        # Return the upload status
        return {
            "status": upload.get("status", "UNKNOWN"),
            "progress": upload.get("progress", ""),
            "progress_percent": upload.get("progress_percent", 0),
            "error_message": upload.get("error", None),
            "updated_at": upload.get("updated_at"),
            "file_path": upload.get("file_path", ""),
            "filename": upload.get("filename", "")
        }
    except InvalidId:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid upload ID format"}
        )
    except Exception as e:
        logging.error(f"Error getting import status: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.get("/admin/import/{upload_id}/status")
async def get_import_status(upload_id: str, request: Request):
    """Get the status of an import"""
    # Get database
    db = request.app.db

    # Convert upload_id to ObjectId
    upload_id = ObjectId(upload_id)

    # Get upload - handle both async and sync MongoDB clients
    is_sync_client = str(type(db)) == "<class 'pymongo.database.Database'>"

    if is_sync_client:  # Sync client
        upload = db.uploads.find_one({"_id": upload_id})
    else:  # Async client
        upload = await db.uploads.find_one({"_id": upload_id})

    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")

    # Return status
    return {
        "status": upload["status"],
        "progress": upload.get("progress"),
        "progress_percent": upload.get("progress_percent", 0),
        "error": upload.get("error")
    }

@app.post("/admin/cancel-import/{upload_id}")
async def cancel_import(upload_id: str):
    """Cancel an in-progress import"""
    try:
        # Convert the upload_id string to ObjectId
        upload_oid = ObjectId(upload_id)
        
        # Find the upload in the database
        upload = await app.db.uploads.find_one({"_id": upload_oid})
        
        if not upload:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "Upload not found"}
            )
        
        # Update status to CANCELLED
        await app.db.uploads.update_one(
            {"_id": upload_oid},
            {"$set": {
                "status": "CANCELLED",
                "progress": "Import cancelled",
                "updated_at": datetime.now(),
                "error": "Import cancelled by user"
            }}
        )
        
        # Return success
        return JSONResponse(
            content={"success": True, "message": "Import cancelled"}
        )
    except InvalidId:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Invalid upload ID format"}
        )
    except Exception as e:
        logging.error(f"Error cancelling import: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )

@app.get("/admin/import/{upload_id}/failed")
async def get_failed_messages(request: Request, upload_id: str):
    """Get failed message parses for an import"""
    try:
        db = request.app.db
        upload_id = ObjectId(upload_id)

        # Get the failed messages
        failed_messages = await db.failed_messages.find(
            {"upload_id": str(upload_id)}
        ).to_list(length=None)

        # Group by channel
        grouped = {}
        for msg in failed_messages:
            channel = msg['channel']
            if channel not in grouped:
                grouped[channel] = []
            grouped[channel].append(msg)

        return templates.TemplateResponse(
            "failed_messages.html",
            {
                "request": request,
                "upload_id": upload_id,
                "channels": grouped
            }
        )

    except Exception as e:
        logger.exception("Error getting failed messages")
        return JSONResponse(
            status_code=500,
            content={"detail": str(e)}
        )

@app.get("/debug/conversations")
async def debug_conversations():
    """Debug endpoint to view raw conversation data"""
    conversations = await app.db.conversations.find({}).to_list(10)
    # Convert datetime objects to strings
    for conv in conversations:
        if "created" in conv and isinstance(conv["created"], datetime):
            conv["created"] = conv["created"].isoformat()
        # Convert ObjectId to string
        if "_id" in conv:
            conv["_id"] = str(conv["_id"])
    return JSONResponse(content={"conversations": conversations})

async def get_system_stats() -> Dict[str, int]:
    """Get system-wide statistics"""
    stats = {
        "total_messages": await app.db.messages.count_documents({}),
        "total_channels": await app.db.conversations.count_documents({"type": "channel"}),
        "total_users": await app.db.conversations.count_documents({"type": {"$in": ["Multi-Party Direct Message", "Direct Message", "dm", "Phone call"]}})
    }
    return stats

async def get_last_import_status() -> Dict[str, Any]:
    """Get status of the last import"""
    status = await app.db.import_status.find_one(
        sort=[("timestamp", -1)]
    )
    return status

@app.post("/admin/import")
async def import_new_messages(request: Request):
    """Import new messages from Slack export"""
    try:
        # Import new messages
        new_messages = await import_slack_export(app.db, Path(DATA_DIR) / "new_messages.zip", "new_messages")

        # Record import status
        await app.db.import_status.insert_one({
            "timestamp": datetime.now(),
            "messages_imported": new_messages,
            "status": "success"
        })

        return RedirectResponse(
            url="/admin",
            status_code=303
        )
    except Exception as e:
        # Log detailed error info
        logging.exception("Import failed with exception:")
        return RedirectResponse(
            url=f"/admin?error=import_failed&message={str(e)}",
            status_code=303
        )

@app.post("/admin/flush")
async def flush_data(request: Request):
    """Delete all imported data"""
    try:
        # Drop all collections
        await app.db.messages.drop()
        await app.db.conversations.drop()
        await app.db.import_status.drop()

        return RedirectResponse(
            url="/admin",
            status_code=303
        )
    except Exception as e:
        # Log error and redirect
        logging.error(f"Flush failed: {str(e)}")
        return RedirectResponse(
            url="/admin?error=flush_failed",
            status_code=303
        )

@app.post("/admin/clear")
async def clear_data(request: Request):
    """Clear selected data types"""
    try:
        form = await request.form()
        clear_messages = form.get("clear_messages") == "on"
        clear_embeddings = form.get("clear_embeddings") == "on"
        clear_uploads = form.get("clear_uploads") == "on"
        clear_conversations = form.get("clear_conversations") == "on"

        if clear_messages:
            await app.db.messages.drop()
            print("Cleared messages")

        if clear_embeddings:
            # Clear Chroma collection
            app.embeddings.clear_all_embeddings()
            print("Cleared embeddings")

        if clear_uploads:
            await app.db.uploads.drop()
            # Clear upload directory
            upload_dir = Path(DATA_DIR) / "uploads"
            if upload_dir.exists():
                for f in upload_dir.glob("*"):
                    if f.is_file():
                        f.unlink()
            # Clear extract directory
            extract_dir = Path(DATA_DIR) / "extracts"
            if extract_dir.exists():
                for f in extract_dir.glob("*"):
                    if f.is_dir():
                        shutil.rmtree(f)
            print("Cleared uploads")

        if clear_conversations:
            await app.db.conversations.drop()
            print("Cleared conversations")

        return RedirectResponse(
            url="/admin?cleared=true",
            status_code=303
        )
    except Exception as e:
        logging.error(f"Clear failed: {str(e)}")
        return RedirectResponse(
            url=f"/admin?error=clear_failed&message={str(e)}",
            status_code=303
        )

@app.post("/admin/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    """Handle file upload"""
    try:
        logging.info(f"Starting upload of {file.filename}")

        # Validate file
        if not file.filename or not file.filename.lower().endswith('.zip'):
            raise HTTPException(status_code=400, detail="Only ZIP files are allowed")

        # Create upload record
        upload_id = ObjectId()
        await app.db.uploads.insert_one({
            "_id": upload_id,
            "filename": file.filename,
            "status": "UPLOADING",
            "created_at": datetime.utcnow(),
            "size": 0,
            "uploaded_size": 0
        })

        logging.info(f"Created upload record with ID {upload_id}")

        # Ensure upload directory exists
        os.makedirs(UPLOAD_DIR, exist_ok=True)

        # Save file with unique name to avoid conflicts
        safe_filename = f"{upload_id}_{secure_filename(file.filename)}"
        file_path = os.path.join(UPLOAD_DIR, safe_filename)

        # Save file in chunks to handle large files
        total_size = 0
        last_update = 0

        with open(file_path, "wb") as buffer:
            while True:
                chunk = await file.read(8 * 1024 * 1024)  # 8MB chunks
                if not chunk:
                    break

                buffer.write(chunk)
                total_size += len(chunk)

                # Only update DB every 100MB to reduce load
                if total_size - last_update > 100 * 1024 * 1024:
                    await app.db.uploads.update_one(
                        {"_id": upload_id},
                        {"$set": {
                            "uploaded_size": total_size,
                            "updated_at": datetime.utcnow()
                        }}
                    )
                    last_update = total_size

        # Update final status
        await app.db.uploads.update_one(
            {"_id": upload_id},
            {"$set": {
                "status": "UPLOADED",
                "size": total_size,
                "uploaded_size": total_size,
                "file_path": str(file_path),
                "updated_at": datetime.utcnow()
            }}
        )

        logging.info(f"Upload complete: {total_size} bytes")

        return JSONResponse({
            "id": str(upload_id),
            "status": "UPLOADED",
            "size": total_size
        })

    except Exception as e:
        logging.error(f"Upload error: {str(e)}", exc_info=True)
        try:
            os.unlink(file_path)
        except FileNotFoundError:
            logger.warning(f"Could not delete file {file_path}, it does not exist")
        try:
            await app.db.uploads.delete_one({"_id": ObjectId(upload_id)})
        except Exception as e:
            logger.error(f"Error deleting upload record: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/search")
async def api_search(
    query: str = Body(...),
    hybrid_alpha: float = Body(0.5),
    limit: int = Body(50)
):
    try:
        logger.info(f"API Search request: query={query}, hybrid_alpha={hybrid_alpha}, limit={limit}")

        # Initialize embeddings service if not already initialized
        if not hasattr(app, 'embeddings') or not app.embeddings:
            logger.info("Initializing embeddings service")
            app.embeddings = EmbeddingService()
            app.embeddings.initialize()

        # Perform semantic search
        logger.info("Performing semantic search")
        search_results = app.embeddings.search(
            query=query,
            limit=limit,
            hybrid_alpha=hybrid_alpha
        )

        # Extract conversation IDs from results, skipping any without conversation_id
        logger.info(f"Got {len(search_results)} results")
        conversation_ids = list(set(
            r["metadata"]["conversation_id"]
            for r in search_results
            if "metadata" in r and "conversation_id" in r["metadata"]
        ))

        # Get conversation details
        conversations = await app.db.conversations.find(
            {"_id": {"$in": conversation_ids}},
            {"name": 1, "type": 1}
        ).to_list(None)
        conv_map = {str(c["_id"]): c for c in conversations}

        # Format results for template
        results = []
        for r in search_results:
            # Skip results without proper metadata
            if "metadata" not in r or "conversation_id" not in r["metadata"]:
                logger.warning(f"Skipping result without proper metadata: {r}")
                continue

            try:
                ts = float(r["metadata"]["timestamp"]) if r["metadata"]["timestamp"] and r["metadata"]["timestamp"].replace('.','').isdigit() else 0
            except (ValueError, TypeError):
                ts = 0
                logger.warning(f"Could not parse timestamp: {r['metadata']['timestamp']}")

            results.append({
                "text": r["text"],
                "conversation": conv_map.get(str(r["metadata"]["conversation_id"]), {"name": "Unknown", "type": "unknown"}),
                "conversation_id": r["metadata"]["conversation_id"],
                "user": r["metadata"].get("user", "unknown"),
                "ts": ts,
                "score": r["similarity"],
                "keyword_match": r.get("keyword_match", False)
            })

        # Sort results by score
        results.sort(key=lambda x: x["score"], reverse=True)

        logger.info("Search completed successfully")
        return {"results": results}
    except Exception as e:
        logger.error(f"Error in api_search: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/import-status")
async def get_import_status():
    """Get status of all imports"""
    try:
        uploads = await app.db.uploads.find().to_list(length=100)

        # Convert MongoDB documents to JSON-serializable format
        serialized_uploads = []
        for upload in uploads:
            # Convert ObjectId to string
            upload["_id"] = str(upload["_id"])

            # Convert datetime objects to ISO format strings
            for key, value in upload.items():
                if isinstance(value, datetime):
                    upload[key] = value.isoformat()

            serialized_uploads.append(upload)

        return serialized_uploads
    except Exception as e:
        logging.error(f"Error getting import status: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.get("/admin/embeddings/train/{upload_id}")
async def train_embeddings_get(request: Request, upload_id: str):
    """Train embeddings for all messages from an import (GET method)"""
    return await train_embeddings(request, upload_id)

@app.post("/admin/embeddings/train/{upload_id}")
async def train_embeddings_post(request: Request, upload_id: str):
    """Train embeddings for all messages from an import (POST method)"""
    return await train_embeddings(request, upload_id)

async def train_embeddings(request: Request, upload_id: str):
    """Train embeddings for all messages from an import"""
    try:
        # Initialize embeddings service if not already initialized
        if not hasattr(app, 'embeddings') or not app.embeddings:
            logger.info("Initializing embeddings service")
            app.embeddings = EmbeddingService()
            app.embeddings.initialize()

        # Get import status from uploads collection
        logger.info(f"Looking for upload {upload_id} in uploads collection")
        query = {"_id": ObjectId(upload_id)}
        logger.info(f"Query: {query}")
        import_status = await app.db.uploads.find_one(query)
        logger.info(f"Found import status: {import_status}")

        if not import_status:
            logger.error(f"Import {upload_id} not found in uploads collection")
            raise HTTPException(status_code=404, detail="Import not found")

        # Update status to running
        logger.info("Updating status to running")
        await app.db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {
                "$set": {
                    "training_status": "running",
                    "training_progress": 0,
                    "training_started": datetime.utcnow(),
                    "training_error": None
                }
            }
        )

        # Get all messages
        logger.info("Getting all messages")
        messages = await app.db.messages.find().to_list(length=None)
        logger.info(f"Found {len(messages)} messages")

        if not messages:
            logger.error("No messages found in database")
            raise Exception("No messages found in database")

        # Add messages to ChromaDB
        logger.info("Adding messages to ChromaDB")
        try:
            await app.embeddings.add_messages(messages)
            logger.info("Successfully added messages to ChromaDB")
        except Exception as e:
            logger.error(f"Error adding messages to ChromaDB: {str(e)}")
            logger.error(traceback.format_exc())

            # Update status to error
            await app.db.uploads.update_one(
                {"_id": ObjectId(upload_id)},
                {
                    "$set": {
                        "training_status": "failed",
                        "training_error": f"Error training embeddings: {str(e)}",
                        "training_progress": 0
                    }
                }
            )
            raise

        # Update status to completed
        logger.info("Updating status to completed")
        await app.db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {"$set": {"training_status": "completed", "training_progress": 100}}
        )
        return RedirectResponse(url="/admin", status_code=303)

    except Exception as e:
        logger.error(f"Error training embeddings: {str(e)}")
        await app.db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {
                "$set": {
                    "training_status": "failed",
                    "training_error": f"Error training embeddings: {str(e)}"
                }
            }
        )
        raise HTTPException(status_code=500, detail=f"Error training embeddings: {str(e)}")

@app.post("/admin/embeddings/reset/{upload_id}")
async def reset_embeddings(request: Request, upload_id: str):
    """Reset embeddings for an import"""
    try:
        # Get import status
        import_status = await app.db.uploads.find_one({"_id": ObjectId(upload_id)})
        if not import_status:
            raise HTTPException(status_code=404, detail="Import not found")

        # Reset status
        await app.db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {
                "$set": {
                    "training_status": None,
                    "training_progress": 0,
                    "training_started": None,
                    "training_error": None
                }
            }
        )

        # Reset ChromaDB collection
        await app.embeddings.reset_collection()

        return {"status": "success"}

    except Exception as e:
        logger.error(f"Error resetting embeddings: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Check health of all dependencies"""
    status = {
        "status": "healthy",
        "mongodb": "unknown",
        "chroma": "unknown",
        "ollama": "unknown",
        "timestamp": datetime.utcnow().isoformat()
    }

    try:
        # Check MongoDB
        await app.db.command("ping")
        status["mongodb"] = "healthy"
    except Exception as e:
        status["mongodb"] = f"unhealthy: {str(e)}"
        status["status"] = "unhealthy"

    try:
        # Check Chroma
        if not app.embeddings:
            app.embeddings = EmbeddingService()
            app.embeddings.initialize()
        collection = app.embeddings.collection
        if not collection:
            raise ValueError("Chroma collection not initialized")
        status["chroma"] = "healthy"
    except Exception as e:
        status["chroma"] = f"unhealthy: {str(e)}"
        status["status"] = "unhealthy"

    try:
        # Check Ollama
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{OLLAMA_URL}/api/tags") as response:
                if response.status != 200:
                    raise ValueError(f"Ollama returned status {response.status}")
                status["ollama"] = "healthy"
    except Exception as e:
        status["ollama"] = f"unhealthy: {str(e)}"
        status["status"] = "unhealthy"

    return status

@app.post("/admin/restart-import/{upload_id}")
async def restart_import(upload_id: str):
    """Restart a cancelled or failed import"""
    try:
        # Convert the upload_id string to ObjectId
        upload_oid = ObjectId(upload_id)
        
        # Find the upload in the database
        upload = await app.db.uploads.find_one({"_id": upload_oid})
        
        if not upload:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "Upload not found"}
            )
        
        # Check if the file exists
        file_path = upload.get("file_path")
        if not file_path or not os.path.exists(file_path):
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Upload file not found"}
            )
        
        # Update status to extracting
        await app.db.uploads.update_one(
            {"_id": upload_oid},
            {"$set": {
                "status": "EXTRACTING",
                "progress": "Starting extraction...",
                "progress_percent": 0,
                "updated_at": datetime.now(),
                "current_stage": "EXTRACTING",
                "stage_progress": 0,
                "error": None
            }}
        )
        
        # Start the extraction process in the background
        asyncio.create_task(extract_and_import(upload_id, file_path))
        
        return JSONResponse(
            content={"success": True, "message": "Import restarted"}
        )
    except InvalidId:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Invalid upload ID format"}
        )
    except Exception as e:
        logging.error(f"Error restarting import: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )

async def import_slack_export(db: AsyncIOMotorClient, extract_path: Path, upload_id: str) -> None:
    """Import a Slack export file"""
    try:
        # Convert upload_id to ObjectId if it's a string
        if isinstance(upload_id, str):
            upload_id_obj = ObjectId(upload_id)
        else:
            upload_id_obj = upload_id

        # Update status to IMPORTING
        await db.uploads.update_one(
            {"_id": upload_id_obj},
            {"$set": {
                "status": "IMPORTING",
                "progress": "Starting import process...",
                "progress_percent": 0,
                "stage_progress": 0,
                "current_stage": "IMPORTING",
                "updated_at": datetime.utcnow()
            }}
        )

        total_files = 0
        processed_files = 0
        total_messages = 0

        # Process channel files
        channels_dir = extract_path / "channels"
        if channels_dir.exists():
            # Count total files for progress tracking
            channel_files = list(channels_dir.rglob("*.txt"))
            total_files += len(channel_files)

            for i, file_path in enumerate(channel_files):
                try:
                    channel, messages = await process_file(db, file_path, upload_id)

                    # Store channel metadata
                    await db.channels.insert_one(channel.model_dump())

                    # Also insert into conversations collection for UI
                    conversation = {
                        "name": channel.name,
                        "type": "dm" if channel.is_dm else "channel",
                        "channel_id": channel.id,
                        "created_at": channel.created,
                        "updated_at": datetime.utcnow(),
                        "topic": channel.topic,
                        "purpose": channel.purpose,
                        "is_archived": channel.is_archived,
                        "dm_users": channel.dm_users if channel.is_dm else []
                    }
                    db.conversations.update_one(
                        {"channel_id": channel.id},
                        {"$set": conversation},
                        upsert=True
                    )

                    # Store messages in batches
                    if messages:
                        # Add conversation_id to messages for UI
                        message_docs = []
                        for msg in messages:
                            msg_dict = msg.model_dump()
                            msg_dict["conversation_id"] = channel.id
                            message_docs.append(msg_dict)

                        await db.messages.insert_many(message_docs)
                        total_messages += len(messages)

                    # Update progress every 10 files
                    processed_files += 1
                    if processed_files % 10 == 0 or processed_files == total_files:
                        percent = int((processed_files / total_files) * 100) if total_files > 0 else 0
                        await db.uploads.update_one(
                            {"_id": upload_id_obj},
                            {"$set": {
                                "progress": f"Importing... {percent}% ({total_messages} messages)",
                                "progress_percent": percent,
                                "stage_progress": percent,
                                "updated_at": datetime.utcnow()
                            }}
                        )

                except Exception as e:
                    logger.error(f"Error importing {file_path}: {str(e)}")
                    await db.failed_imports.insert_one({
                        "upload_id": upload_id,
                        "file": str(file_path),
                        "error": str(e),
                        "timestamp": datetime.utcnow()
                    })

        # Process DM files
        dms_dir = extract_path / "dms"
        if dms_dir.exists():
            # Count total files for progress tracking
            dm_files = list(dms_dir.rglob("*.txt"))
            dm_total = len(dm_files)
            total_files += dm_total

            for i, file_path in enumerate(dm_files):
                try:
                    channel, messages = await process_file(db, file_path, upload_id)

                    # Store channel metadata
                    await db.channels.insert_one(channel.model_dump())

                    # Also insert into conversations collection for UI
                    conversation = {
                        "name": channel.name,
                        "type": "dm" if channel.is_dm else "channel",
                        "channel_id": channel.id,
                        "created_at": channel.created,
                        "updated_at": datetime.utcnow(),
                        "topic": channel.topic,
                        "purpose": channel.purpose,
                        "is_archived": channel.is_archived,
                        "dm_users": channel.dm_users if channel.is_dm else []
                    }
                    db.conversations.update_one(
                        {"channel_id": channel.id},
                        {"$set": conversation},
                        upsert=True
                    )

                    # Store messages in batches
                    if messages:
                        # Add conversation_id to messages for UI
                        message_docs = []
                        for msg in messages:
                            msg_dict = msg.model_dump()
                            msg_dict["conversation_id"] = channel.id
                            message_docs.append(msg_dict)

                        await db.messages.insert_many(message_docs)
                        total_messages += len(messages)

                    # Update progress every 10 files
                    processed_files += 1
                    if processed_files % 10 == 0 or processed_files == total_files:
                        percent = int((processed_files / total_files) * 100) if total_files > 0 else 0
                        await db.uploads.update_one(
                            {"_id": upload_id_obj},
                            {"$set": {
                                "progress": f"Importing... {percent}% ({total_messages} messages)",
                                "progress_percent": percent,
                                "stage_progress": percent,
                                "updated_at": datetime.utcnow()
                            }}
                        )

                except Exception as e:
                    logger.error(f"Error importing {file_path}: {str(e)}")
                    await db.failed_imports.insert_one({
                        "upload_id": upload_id,
                        "file": str(file_path),
                        "error": str(e),
                        "timestamp": datetime.utcnow()
                    })

        # Update status to IMPORTED when complete
        await db.uploads.update_one(
            {"_id": upload_id_obj},
            {"$set": {
                "status": "IMPORTED",
                "progress": f"Import complete: {total_messages} messages from {processed_files} files",
                "progress_percent": 100,
                "stage_progress": 100,
                "current_stage": "COMPLETE",
                "updated_at": datetime.utcnow()
            }}
        )

    except Exception as e:
        logger.error(f"Error importing from {extract_path}: {str(e)}")
        # Update status to ERROR
        if isinstance(upload_id, str):
            upload_id_obj = ObjectId(upload_id)
        else:
            upload_id_obj = upload_id

        await db.uploads.update_one(
            {"_id": upload_id_obj},
            {"$set": {
                "status": "ERROR",
                "progress": f"Import failed: {str(e)}",
                "error": str(e),
                "updated_at": datetime.utcnow()
            }}
        )
        raise

# Add synchronous versions of our async functions
def extract_with_progress_sync(db, zip_path: str, extract_path: Path, upload_id: ObjectId):
    """Extract ZIP file with progress updates - synchronous version"""
    print(f"Starting extraction with progress from {zip_path} to {extract_path}")
    total_size = get_zip_total_size(zip_path)
    extracted_size = 0

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        for file_info in zip_ref.infolist():
            print(f"Extracting {file_info.filename}")
            zip_ref.extract(file_info, extract_path)
            extracted_size += file_info.file_size
            percent = int((extracted_size / total_size) * 100)

            # Update progress every 5%
            if percent % 5 == 0:
                db.uploads.update_one(
                    {"_id": upload_id},
                    {"$set": {
                        "progress": f"Extracting... {percent}%",
                        "progress_percent": percent,
                        "stage_progress": percent,
                        "updated_at": datetime.utcnow()
                    }}
                )

    print("Extraction complete")

    # Update status to EXTRACTED when complete
    db.uploads.update_one(
        {"_id": upload_id},
        {"$set": {
            "status": "EXTRACTED",
            "progress": "Extraction complete",
            "progress_percent": 100,
            "updated_at": datetime.utcnow()
        }}
    )

def import_slack_export_sync(db, extract_path: Path, upload_id: str):
    """Import a Slack export file - synchronous version"""
    print(f"=== IMPORT_SLACK_EXPORT_SYNC STARTED ===")
    print(f"Importing from {extract_path}")
    print(f"Upload ID: {upload_id}")
    print(f"DB type: {type(db)}")

    # Convert upload_id to ObjectId if it's a string
    if isinstance(upload_id, str):
        upload_id = ObjectId(upload_id)
        print(f"Converted upload_id to ObjectId: {upload_id}")

    # Update status to IMPORTING
    try:
        db.uploads.update_one(
            {"_id": upload_id},
            {"$set": {
                "status": "IMPORTING",
                "progress": "Starting import process...",
                "progress_percent": 0,
                "updated_at": datetime.utcnow()
            }}
        )
        print("Updated status to IMPORTING")
    except Exception as e:
        print(f"Error updating status to IMPORTING: {e}")

    # Get list of channel files
    try:
        channel_files = list(extract_path.glob("**/*.txt"))
        total_files = len(channel_files)
        print(f"Found {total_files} channel files in {extract_path}")

        if total_files == 0:
            print(f"WARNING: No channel files found in {extract_path}")
            # List the directory contents to debug
            print(f"Directory contents of {extract_path}:")
            for item in extract_path.iterdir():
                print(f"  - {item}")
    except Exception as e:
        print(f"Error getting channel files: {e}")
        total_files = 0
        channel_files = []

    # Process each channel file
    total_messages = 0
    users = {}  # Track users across all files

    for i, channel_file in enumerate(channel_files):
        print(f"Processing file {i+1}/{total_files}: {channel_file}")
        try:
            # Process the file
            channel, messages = process_file(db, channel_file, upload_id, sync=True)

            # Store channel metadata
            print(f"Storing channel metadata for {channel.name}")
            result = db.channels.insert_one(channel.model_dump())
            print(f"Channel inserted with ID: {result.inserted_id}")

            # Also insert into conversations collection for UI
            conversation = {
                "name": channel.name,
                "type": "dm" if channel.is_dm else "channel",
                "channel_id": channel.id,
                "created_at": channel.created,
                "updated_at": datetime.utcnow(),
                "topic": channel.topic,
                "purpose": channel.purpose,
                "is_archived": channel.is_archived,
                "dm_users": channel.dm_users if channel.is_dm else []
            }
            db.conversations.update_one(
                {"channel_id": channel.id},
                {"$set": conversation},
                upsert=True
            )
            print(f"Conversation inserted for UI")

            # Store messages in batches
            if messages:
                print(f"Storing {len(messages)} messages")
                # Add conversation_id to messages for UI
                message_docs = []
                for msg in messages:
                    msg_dict = msg.model_dump()
                    msg_dict["conversation_id"] = channel.id
                    message_docs.append(msg_dict)

                    # Track users
                    if msg.username not in users:
                        users[msg.username] = {
                            "username": msg.username,
                            "first_seen": msg.ts,
                            "last_seen": msg.ts,
                            "channels": {channel.id},
                            "message_count": 1
                        }
                    else:
                        user = users[msg.username]
                        user["first_seen"] = min(user["first_seen"], msg.ts)
                        user["last_seen"] = max(user["last_seen"], msg.ts)
                        user["channels"].add(channel.id)
                        user["message_count"] += 1

                result = db.messages.insert_many(message_docs)
                print(f"Inserted {len(result.inserted_ids)} messages")
                total_messages += len(messages)

            # Update progress
            percent = int(((i + 1) / total_files) * 100)
            db.uploads.update_one(
                {"_id": upload_id},
                {"$set": {
                    "progress": f"Importing channels... {percent}% ({total_messages} messages)",
                    "progress_percent": percent,
                    "stage_progress": percent,
                    "updated_at": datetime.utcnow()
                }}
            )
            print(f"Updated progress: {percent}%")
        except Exception as e:
            print(f"Error processing {channel_file}: {e}")
            # Log the error but continue with other files
            db.failed_imports.insert_one({
                "upload_id": upload_id,
                "file": str(channel_file),
                "error": str(e),
                "timestamp": datetime.utcnow()
            })

    # Insert/update users
    for username, user in users.items():
        db.users.update_one(
            {"username": username},
            {
                "$set": {
                    "username": username,
                    "first_seen": user["first_seen"],
                    "last_seen": user["last_seen"],
                    "channels": list(user["channels"]),
                    "message_count": user["message_count"]
                }
            },
            upsert=True
        )
        print(f"User {username} inserted/updated")

    # Update status to IMPORTED
    try:
        db.uploads.update_one(
            {"_id": upload_id},
            {"$set": {
                "status": "IMPORTED",
                "progress": f"Import complete: {total_messages} messages from {total_files} files",
                "progress_percent": 100,
                "updated_at": datetime.utcnow()
            }}
        )
        print(f"Updated status to IMPORTED. Processed {total_files} files with {total_messages} messages.")
    except Exception as e:
        print(f"Error updating status to IMPORTED: {e}")

    print("=== IMPORT_SLACK_EXPORT_SYNC COMPLETED ===")

@app.get("/admin/debug", response_class=HTMLResponse)
async def debug_page(request: Request):
    """Debug page to help diagnose UI issues"""
    # Get a database connection
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[MONGO_DB]

    # Get all uploads
    uploads = await db.uploads.find().to_list(length=100)

    # Convert ObjectId to string for JSON serialization
    for upload in uploads:
        upload["_id"] = str(upload["_id"])

    # Simplified debug page without template extraction
    return templates.TemplateResponse(
        "debug.html",
        {
            "request": request,
            "uploads": uploads,
            "uploads_json": json.dumps(uploads, indent=2),
            "server_template": "Disabled for debugging",
            "js_template": "Disabled for debugging"
        }
    )

@app.post("/admin/start-import/{upload_id}")
async def start_import(upload_id: str):
    """Start the import process for an uploaded file"""
    try:
        # Get the upload
        upload = await app.db.uploads.find_one({"_id": ObjectId(upload_id)})
        if not upload:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "Upload not found"}
            )

        # Check if the file exists
        file_path = upload.get("file_path")
        if not file_path or not os.path.exists(file_path):
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Upload file not found"}
            )

        # Update status to extracting
        await app.db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {"$set": {
                "status": "EXTRACTING",
                "progress": "Starting extraction...",
                "progress_percent": 0,
                "updated_at": datetime.now(),
                "current_stage": "EXTRACTING",
                "stage_progress": 0,
                "error": None
            }}
        )

        # Start the extraction process in the background
        asyncio.create_task(extract_and_import(upload_id, file_path))

        return JSONResponse(
            content={"success": True, "message": "Import started"}
        )
    except Exception as e:
        logging.error(f"Error starting import: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )

async def extract_and_import(upload_id: str, file_path: str):
    """Extract and import a Slack export file"""
    try:
        # Create a temporary directory for extraction
        temp_dir = os.path.join(tempfile.gettempdir(), f"slack_extract_{upload_id}")
        os.makedirs(temp_dir, exist_ok=True)

        # Extract the ZIP file
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            total_files = len(zip_ref.namelist())
            for i, file in enumerate(zip_ref.namelist()):
                zip_ref.extract(file, temp_dir)

                # Update progress every 10 files or for the last file
                if i % 10 == 0 or i == total_files - 1:
                    progress_percent = int((i + 1) / total_files * 100)
                    await app.db.uploads.update_one(
                        {"_id": ObjectId(upload_id)},
                        {"$set": {
                            "progress": f"Extracting files... {i+1}/{total_files}",
                            "progress_percent": progress_percent,
                            "updated_at": datetime.now(),
                            "stage_progress": progress_percent
                        }}
                    )

        # Update status to EXTRACTED
        await app.db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {"$set": {
                "status": "EXTRACTED",
                "progress": "Extraction complete. Click play to start importing.",
                "progress_percent": 100,
                "updated_at": datetime.now(),
                "current_stage": "EXTRACTED",
                "stage_progress": 100,
                "extract_path": temp_dir
            }}
        )

    except Exception as e:
        logging.error(f"Error in extract_and_import: {str(e)}")
        # Update status to ERROR
        await app.db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {"$set": {
                "status": "ERROR",
                "progress": f"Error: {str(e)}",
                "updated_at": datetime.now(),
                "error": str(e)
            }}
        )
        # Clean up the temporary directory if it exists
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

async def start_import_process(upload_id: str):
    """Start the import process for an extracted upload"""
    try:
        # Get the upload
        upload = await app.db.uploads.find_one({"_id": ObjectId(upload_id)})
        if not upload:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "Upload not found"}
            )

        # Check if the extract path exists
        extract_path = upload.get("extract_path")
        if not extract_path or not os.path.exists(extract_path):
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Extracted files not found"}
            )

        # Update status to IMPORTING
        await app.db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {"$set": {
                "status": "IMPORTING",
                "progress": "Starting import...",
                "progress_percent": 0,
                "updated_at": datetime.now(),
                "current_stage": "IMPORTING",
                "stage_progress": 0
            }}
        )

        # Import the extracted files
        # This is a placeholder - you would need to implement the actual import logic
        # based on your application's requirements
        await asyncio.sleep(2)  # Simulate some processing time

        # Update status to COMPLETED
        await app.db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {"$set": {
                "status": "COMPLETED",
                "progress": "Import complete",
                "progress_percent": 100,
                "updated_at": datetime.now(),
                "current_stage": "COMPLETED",
                "stage_progress": 100
            }}
        )

        # Clean up the temporary directory
        shutil.rmtree(extract_path, ignore_errors=True)

        return JSONResponse(
            content={"success": True, "message": "Import completed successfully"}
        )
    except Exception as e:
        logging.error(f"Error in start_import_process: {str(e)}")
        # Update status to ERROR
        await app.db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {"$set": {
                "status": "ERROR",
                "progress": f"Error: {str(e)}",
                "updated_at": datetime.now(),
                "error": str(e)
            }}
        )
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )

@app.post("/admin/start-import-process/{upload_id}")
async def start_import_endpoint(upload_id: str):
    """Start the import process for an extracted upload"""
    try:
        # Get the upload
        upload = await app.db.uploads.find_one({"_id": ObjectId(upload_id)})
        if not upload:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "Upload not found"}
            )

        # Check if the upload is in the correct state
        status = upload.get("status", "").lower()
        if status != "extracted":
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"Upload is not in EXTRACTED state (current: {status})"}
            )

        # Start the import process in the background
        asyncio.create_task(start_import_process(upload_id))

        return JSONResponse(
            content={"success": True, "message": "Import process started"}
        )
    except Exception as e:
        logging.error(f"Error starting import process: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )
