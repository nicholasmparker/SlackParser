from fastapi import FastAPI, Request, Query, HTTPException, Body, File, UploadFile
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional, Dict, Any, List
import os
from pathlib import Path
from datetime import datetime
import logging
from pydantic import BaseModel
from app.embeddings import EmbeddingService
from bson import ObjectId
from fastapi import status
from werkzeug.utils import secure_filename
import asyncio
import shutil
import json
import aiohttp
from app.db.models import Channel, Message, Upload, FailedImport
from app.importer.importer import process_file, import_slack_export
from app.importer.parser import parse_message, parse_channel_metadata, parse_dm_metadata, ParserError
import glob
import zipfile

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
    pipeline = [
        {"$match": {"_id": conversation_id}},
        {"$project": {
            "_id": 1,
            "name": {"$ifNull": ["$name", "$_id"]},
            "type": 1,
            "display_name": {
                "$cond": {
                    "if": {"$eq": ["$type", "dm"]},
                    "then": {
                        "$reduce": {
                            "input": {
                                "$map": {
                                    "input": {"$split": [{"$ifNull": ["$name", "$_id"]}, "-"]},
                                    "as": "name",
                                    "in": {
                                        "$cond": {
                                            "if": {"$regexMatch": {"input": "$$name", "regex": "^U\\d+"}},
                                            "then": {"$substrCP": ["$$name", 0, 2]},  # Just take U7 from U7WB86M7W
                                            "else": "$$name"
                                        }
                                    }
                                }
                            },
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
        }}
    ]
    conversation = await app.db.conversations.aggregate(pipeline).next()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Build query
    query = {"conversation_id": conversation_id}
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
    conversation_ids = [c["_id"] for c in conversations]
    message_counts = await app.db.messages.aggregate([
        {"$match": {"conversation_id": {"$in": conversation_ids}}},
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
        conv_id = str(conv["_id"])
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
            conversation_ids = list(set(r["metadata"]["channel"] for r in search_results))

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
                    "conversation": conv_map.get(str(r["metadata"]["channel"]), {"name": "Unknown", "type": "unknown"}),
                    "conversation_id": r["metadata"]["channel"],
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
    """Start importing a Slack export."""
    print(f"\n=== Starting import for {upload_id} ===")
    try:
        # Get database
        db = request.app.db

        # Convert upload_id to ObjectId
        upload_id = ObjectId(upload_id)
        print(f"Looking up upload {upload_id}")

        # Get upload
        upload = await db.uploads.find_one({"_id": upload_id})
        if not upload:
            print(f"Upload {upload_id} not found!")
            raise HTTPException(status_code=404, detail="Upload not found")

        print(f"Found upload: {upload}")

        # Create extract directory
        extract_path = Path("/data/extracts") / str(upload_id)
        print(f"Creating extract directory: {extract_path}")
        extract_path.mkdir(parents=True, exist_ok=True)

        # Update status to extracting
        print("Updating status to EXTRACTING")
        await db.uploads.update_one(
            {"_id": upload_id},
            {"$set": {
                "status": "EXTRACTING",
                "progress": "Starting extraction...",
                "progress_percent": 0,
                "updated_at": datetime.utcnow()
            }}
        )

        print(f"Starting extraction from {upload['file_path']}")
        # Extract zip file
        await extract_with_progress(db, str(upload["file_path"]), extract_path, upload_id)

        print("Extraction complete, updating status to IMPORTING")
        # Update status back to importing
        await db.uploads.update_one(
            {"_id": upload_id},
            {"$set": {
                "status": "IMPORTING",
                "progress": "Starting import...",
                "progress_percent": 0,
                "updated_at": datetime.utcnow()
            }}
        )

        print("Starting import task")
        # Start import in background
        task = asyncio.create_task(
            import_slack_export(db, extract_path, upload_id)
        )

        print("=== Import started successfully ===\n")
        return {"status": "ok"}

    except Exception as e:
        print(f"Error starting import: {str(e)}")
        logger.exception("Error starting import")
        raise

@app.get("/admin/import/{upload_id}/status")
async def get_import_status(upload_id: str, request: Request):
    """Get the status of an import"""
    # Get database
    db = request.app.db

    # Convert upload_id to ObjectId
    upload_id = ObjectId(upload_id)

    # Get upload
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

@app.post("/admin/import/{upload_id}/cancel")
async def cancel_import(request: Request, upload_id: str):
    """Cancel a stuck import"""
    try:
        db = app.db
        upload_id = ObjectId(upload_id)
        upload = await db.uploads.find_one({"_id": upload_id})

        if not upload:
            return JSONResponse(
                status_code=404,
                content={"detail": "Upload not found"}
            )

        # Only allow cancelling if in an active state
        active_states = ["extracting", "importing_channels", "importing_dms", "generating_embeddings", "IMPORTING"]
        if upload["status"] not in active_states:
            return JSONResponse(
                status_code=400,
                content={"detail": f"Cannot cancel import that is not in progress. Current status: {upload['status']}"}
            )

        # Update status to cancelled
        await db.uploads.update_one(
            {"_id": upload_id},
            {
                "$set": {
                    "status": "cancelled",
                    "error": None,
                    "progress": "Import cancelled by user",
                    "progress_percent": 0,
                    "updated_at": datetime.utcnow()
                }
            }
        )

        return {"status": "cancelled"}

    except Exception as e:
        logger.exception("Error cancelling import")
        return JSONResponse(
            status_code=500,
            content={"detail": str(e)}
        )

@app.get("/admin/import/{upload_id}/failed")
async def get_failed_messages(request: Request, upload_id: str):
    """Get failed message parses for an import"""
    try:
        db = app.db
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
            await app.embeddings.clear_collection()
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
            url="/admin",
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
        search_results = await app.embeddings.search(
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

@app.post("/admin/embeddings/train/{upload_id}")
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

        # Get all conversations
        logger.info("Getting all conversations")
        conversations = await app.db.conversations.find().to_list(length=None)
        if not conversations:
            logger.info("No conversations found, checking collection exists")
            collections = await app.db.list_collection_names()
            logger.info(f"Collections in database: {collections}")
            sample = await app.db.messages.find_one()
            logger.info(f"Sample message: {sample}")
            raise Exception("No conversations found in database")

        conversation_ids = [conv["_id"] for conv in conversations]
        logger.info(f"Found {len(conversation_ids)} conversations: {conversation_ids}")

        # Get messages for all conversations
        logger.info("Getting messages for all conversations")
        messages = await app.db.messages.find({"conversation_id": {"$in": conversation_ids}}).to_list(length=None)
        logger.info(f"Found {len(messages)} messages")

        if not messages:
            logger.error("No messages found in any conversations")
            raise Exception("No messages found in any conversations")

        # Add messages to ChromaDB
        logger.info("Adding messages to ChromaDB")
        try:
            await app.embeddings.add_messages(messages)
            logger.info("Successfully added messages to ChromaDB")
        except Exception as e:
            logger.error(f"Error adding messages to ChromaDB: {str(e)}")
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

@app.post("/api/restart_import/{upload_id}")
async def restart_import(upload_id: str):
    """Restart a failed or uploaded import"""
    try:
        # Get the upload record
        upload = await app.db.uploads.find_one({"_id": ObjectId(upload_id)})
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")

        # Only allow restarting failed, cancelled, or uploaded imports
        if upload["status"] not in ["ERROR", "cancelled", "UPLOADED"]:
            raise HTTPException(status_code=400, detail="Can only restart failed, cancelled, or uploaded imports")

        # Start the import
        file_path = Path(upload["file_path"])
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Upload file not found")

        # Update status to start fresh
        await app.db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {"$set": {
                "status": "UPLOADED",
                "error": None,
                "progress": None,
                "progress_percent": 0,
                "updated_at": datetime.utcnow()
            }}
        )

        # Get extract path
        extract_path = Path("/data/extracts") / str(upload_id)

        # Start import in background
        task = asyncio.create_task(
            import_slack_export(app.db, extract_path, upload_id)
        )

        # Add error handling for the background task
        def handle_import_completion(task):
            try:
                task.result()  # This will raise any exceptions from the task
            except Exception as e:
                logger.exception("Import failed")
                asyncio.create_task(
                    app.db.uploads.update_one(
                        {"_id": ObjectId(upload_id)},
                        {"$set": {
                            "status": "ERROR",
                            "error": str(e),
                            "updated_at": datetime.utcnow()
                        }}
                    )
                )

        task.add_done_callback(handle_import_completion)

        return {"status": "success"}

    except Exception as e:
        logger.error(f"Error restarting import: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def import_slack_export(db: AsyncIOMotorClient, extract_path: Path, upload_id: str) -> None:
    """Import a Slack export file"""
    try:
        # Process channel files
        channels_dir = extract_path / "channels"
        if channels_dir.exists():
            for file_path in channels_dir.rglob("*.txt"):
                try:
                    channel, messages = await process_file(db, file_path, upload_id)

                    # Store channel metadata
                    await db.channels.insert_one(channel.model_dump())

                    # Store messages in batches
                    if messages:
                        await db.messages.insert_many([m.model_dump() for m in messages])

                except Exception as e:
                    logger.error(f"Error importing {file_path}: {str(e)}")
                    await db.failed_imports.insert_one({
                        "file": str(file_path),
                        "error": str(e),
                        "upload_id": upload_id,
                        "timestamp": datetime.utcnow()
                    })

        # Process DM files
        dms_dir = extract_path / "dms"
        if dms_dir.exists():
            for file_path in dms_dir.rglob("*.txt"):
                try:
                    channel, messages = await process_file(db, file_path, upload_id)

                    # Store channel metadata
                    await db.channels.insert_one(channel.model_dump())

                    # Store messages in batches
                    if messages:
                        await db.messages.insert_many([m.model_dump() for m in messages])

                except Exception as e:
                    logger.error(f"Error importing {file_path}: {str(e)}")
                    await db.failed_imports.insert_one({
                        "file": str(file_path),
                        "error": str(e),
                        "upload_id": upload_id,
                        "timestamp": datetime.utcnow()
                    })

    except Exception as e:
        logger.error(f"Error importing from {extract_path}: {str(e)}")
        raise
