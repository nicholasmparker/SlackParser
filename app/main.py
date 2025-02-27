"""Main application file for the SlackParser."""

import os
import logging
import asyncio
import zipfile
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path
from bson import ObjectId
from bson.errors import InvalidId
import json

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, BackgroundTasks, Body, Query, Depends
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.cors import CORSMiddleware

# Import services
from app.services.main_service import MainService
from app.db.mongo import get_db, get_sync_db
from app.services.search_service import SearchService  # Import SearchService

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="SlackParser")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set up static files and templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Define template filters
def timedelta_filter(value):
    """Format a timedelta for display."""
    if not value:
        return ""

    if isinstance(value, (int, float)):
        value = timedelta(seconds=value)

    if not isinstance(value, timedelta):
        return str(value)

    total_seconds = value.total_seconds()

    if total_seconds < 60:
        return f"{int(total_seconds)} seconds"
    elif total_seconds < 3600:
        return f"{int(total_seconds / 60)} minutes"
    elif total_seconds < 86400:
        return f"{int(total_seconds / 3600)} hours"
    else:
        return f"{int(total_seconds / 86400)} days"

def strftime_filter(value, fmt="%Y-%m-%d %H:%M:%S"):
    """Format a date according to the given format.

    For messages, we follow Slack's display logic:
    - Messages from today: show only time (3:56 PM)
    - Messages from this week: show day and time (Wed 3:56 PM)
    - Older messages: show date and time (Feb 24, 2022 3:56 PM)
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
            return value.strftime("%b %d, %Y %I:%M %p").lstrip("0")

    except Exception as e:
        logging.error(f"Error formatting timestamp: {str(e)}")
        return str(value)

def from_json_filter(value):
    """Parse a JSON string into a Python object"""
    if not value:
        return None
    try:
        return json.loads(value)
    except:
        return None

# Initialize templates
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["strftime"] = strftime_filter
templates.env.filters["timedelta"] = timedelta_filter
templates.env.filters["from_json"] = from_json_filter

# Environment variables
DATA_DIR = os.getenv("DATA_DIR", "/data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
EXTRACT_DIR = os.path.join(DATA_DIR, "extracts")

# Ensure directories exist
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(EXTRACT_DIR, exist_ok=True)

# Initialize services
@app.on_event("startup")
async def startup_db_client():
    """Initialize database and services on startup."""
    app.db = get_db()
    app.sync_db = get_sync_db()
    app.service = MainService(db=app.db, sync_db=app.sync_db)

    # Create indexes
    await app.db.messages.create_index([("text", "text")])
    await app.db.messages.create_index([("conversation_id", 1)])
    await app.db.messages.create_index([("ts", 1)])
    await app.db.conversations.create_index([("channel_id", 1)], unique=True)
    await app.db.uploads.create_index([("created_at", -1)])

@app.on_event("shutdown")
async def shutdown_db_client():
    """Close database connections on shutdown."""
    # No need to close Motor client as it manages its own connection pool

# Routes
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render the index page."""
    # Get recent uploads
    uploads = await app.db.uploads.find().sort("created_at", -1).limit(5).to_list(length=5)
    for upload in uploads:
        upload["id"] = str(upload["_id"])

    # Get conversation stats
    channel_count = await app.db.conversations.count_documents({"type": "channel"})
    dm_count = await app.db.conversations.count_documents({"type": "dm"})
    message_count = await app.db.messages.count_documents({})

    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "uploads": uploads,
            "channel_count": channel_count,
            "dm_count": dm_count,
            "message_count": message_count
        }
    )

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    """Admin dashboard"""
    # Get conversation stats
    channel_count = await app.db.conversations.count_documents({"type": "channel"})
    dm_count = await app.db.conversations.count_documents({"type": "dm"})
    message_count = await app.db.messages.count_documents({})

    stats = {
        "channel_count": channel_count,
        "dm_count": dm_count,
        "message_count": message_count
    }

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

        uploads.append(upload)

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "stats": stats,
            "uploads": uploads
        }
    )

@app.post("/admin/upload")
async def admin_upload_file(request: Request, file: UploadFile = File(...)):
    """Handle file upload from admin page"""
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
        safe_filename = f"{upload_id}_{file.filename.replace(' ', '_')}"
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
        except (FileNotFoundError, UnboundLocalError):
            logging.warning(f"Could not delete file, it may not exist")
        try:
            if 'upload_id' in locals():
                await app.db.uploads.delete_one({"_id": upload_id})
        except Exception as e:
            logging.error(f"Error deleting upload record: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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

@app.get("/conversations", response_class=HTMLResponse)
async def conversations(
    request: Request,
    page: int = Query(1, ge=1),
    q: str = "",
    type: str = "all"
):
    """List all conversations (channels and DMs)"""
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
            "created": 1,  # Include created timestamp for sorting
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
        {"$sort": {"created": -1}},  # Sort by created timestamp, most recent first
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

@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request, q: str = "", hybrid_alpha: float = 0.5):
    """Search page for finding messages"""
    results = []
    if q:
        try:
            # Initialize search service if not already initialized
            if not hasattr(app, 'service') or not hasattr(app.service, 'search_service'):
                logger.error("Search service not initialized")
                raise HTTPException(status_code=500, detail="Search service not initialized")

            # Perform semantic search
            results = await app.service.search_service.search(
                query=q,
                limit=50,
                hybrid_alpha=hybrid_alpha
            )

            # No need to reformat the results, they already have all the information we need

        except Exception as e:
            logging.error(f"Error in search_page: {str(e)}", exc_info=True)
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

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Handle file upload."""
    try:
        result = await app.service.upload_service.upload_file(file)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"Upload error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/uploads")
async def list_uploads():
    """List all uploads."""
    try:
        uploads = await app.service.upload_service.list_uploads()
        return JSONResponse(uploads)
    except Exception as e:
        logger.error(f"List uploads error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/uploads/{upload_id}")
async def get_upload(upload_id: str):
    """Get upload by ID."""
    try:
        upload = await app.service.upload_service.get_upload(upload_id)
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")
        return JSONResponse(upload)
    except Exception as e:
        logger.error(f"Get upload error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/uploads/{upload_id}")
async def delete_upload(upload_id: str):
    """Delete upload by ID."""
    try:
        success = await app.service.upload_service.delete_upload(upload_id)
        if not success:
            raise HTTPException(status_code=404, detail="Upload not found")
        return JSONResponse({"status": "deleted"})
    except Exception as e:
        logger.error(f"Delete upload error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search")
async def semantic_search(
    query: str = Form(...),
    hybrid_alpha: float = Form(0.5),
    limit: int = Form(50)
):
    """Search for messages using hybrid search."""
    try:
        results = await app.service.search_service.search(
            query=query,
            limit=limit,
            hybrid_alpha=hybrid_alpha
        )
        return JSONResponse(results)
    except Exception as e:
        logger.error(f"Error in semantic_search: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/search")
async def api_search(
    request: Request,
    query: str = Body(...),
    hybrid_alpha: float = Body(0.5),
    limit: int = Body(50)
):
    """API endpoint for search."""
    try:
        logger.info(f"API Search request: query={query}, hybrid_alpha={hybrid_alpha}, limit={limit}")

        results = await app.service.search_service.search(
            query=query,
            limit=limit,
            hybrid_alpha=hybrid_alpha
        )

        # Format results for API
        formatted_results = []
        for r in results:
            formatted_results.append({
                "text": r["text"],
                "conversation": {
                    "id": r["conversation_id"],
                    "name": r["conversation"].get("name", "Unknown"),
                    "type": r["conversation"].get("type", "unknown")
                },
                "conversation_id": r["conversation_id"],
                "user": r["user"],
                "username": r.get("username", ""),
                "timestamp": r["ts"],
                "ts": r["ts"],
                "score": r["score"]
            })

        return JSONResponse({
            "results": formatted_results,
            "count": len(formatted_results),
            "query": query
        })
    except Exception as e:
        logger.error(f"Error in api_search: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/conversations")
async def list_conversations():
    """List all conversations."""
    try:
        conversations = await app.db.conversations.find().to_list(length=1000)
        for conv in conversations:
            conv["id"] = str(conv["_id"])
        return JSONResponse(conversations)
    except Exception as e:
        logger.error(f"List conversations error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/conversations/{conversation_id}", response_class=HTMLResponse)
async def get_conversation(
    request: Request,
    conversation_id: str,
    page: int = Query(1, ge=1),
    q: Optional[str] = None,
    ts: Optional[float] = None
):
    """Get conversation by ID with messages."""
    try:
        page_size = 50

        # Try to get conversation by channel_id first
        conversation = await app.db.conversations.find_one({"channel_id": conversation_id})

        # If not found, try by _id (in case it's a MongoDB ObjectId)
        if not conversation:
            try:
                conversation = await app.db.conversations.find_one({"_id": ObjectId(conversation_id)})
            except:
                # If conversion to ObjectId fails, it's not a valid ObjectId
                pass

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
            query["text"] = {"$regex": q, "$options": "i"}

        # If we have a timestamp in the URL, find which page it's on
        if ts is not None:
            # Count messages before this timestamp
            count_before = await app.db.messages.count_documents({
                **query,
                "ts": {"$gte": ts}  # Count messages after this one since we sort descending
            })
            # Calculate which page this message is on
            page = (count_before // page_size) + 1

        skip = (page - 1) * page_size

        # Get messages with sorting
        pipeline = [
            {"$match": query},
            {"$sort": {"ts": -1}},
            {"$skip": skip},
            {"$limit": page_size},
            # Add user_name field if not present
            {"$addFields": {
                "user_name": {
                    "$ifNull": [
                        # Try username from message
                        "$username",
                        # Try user_name from message
                        "$user_name",
                        # Fallback to user field
                        "$user"
                    ]
                }
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
    except Exception as e:
        logger.error(f"Get conversation error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/context/{conversation_id}/{timestamp}")
async def get_message_context(conversation_id: str, timestamp: float, context_size: int = 5):
    """Get context messages around a specific message."""
    try:
        context = await app.service.search_service.get_context(
            conversation_id=conversation_id,
            message_ts=timestamp,
            context_size=context_size
        )
        return JSONResponse(context)
    except Exception as e:
        logger.error(f"Get context error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/extract/{upload_id}/start")
async def admin_start_extract(upload_id: str):
    """Start the extraction process for an upload."""
    try:
        # Get the upload record
        upload = await app.db.uploads.find_one({"_id": ObjectId(upload_id)})
        if not upload:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "Upload not found"}
            )

        # Create extract directory path
        extract_dir = Path(f"/data/extracts/{upload_id}")

        # Start extraction in the background
        asyncio.create_task(
            app.service.extraction_service.extract_with_progress(
                zip_path=upload["file_path"],
                extract_dir=extract_dir,
                upload_id=upload_id
            )
        )

        return JSONResponse({"success": True, "message": "Extraction started"})
    except Exception as e:
        logger.error(f"Extract error: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Error starting extraction: {str(e)}"}
        )

@app.post("/admin/import/{upload_id}/start")
async def admin_start_import(upload_id: str):
    """Start the import process for an upload."""
    try:
        # Get upload
        upload = await app.db.uploads.find_one({"_id": ObjectId(upload_id)})
        if not upload:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "Upload not found"}
            )

        # Start import process
        result = await app.service.import_service.start_import_process(upload_id)

        return JSONResponse({"success": True, "message": "Import started"})
    except Exception as e:
        logger.error(f"Import error: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Error starting import: {str(e)}"}
        )

@app.post("/admin/clear-all")
async def admin_clear_all_post(request: Request):
    """Clear all data from the database and file system (POST method)"""
    try:
        main_service = MainService(db=app.db)
        result = await main_service.clear_all_data()
        return {"status": "success", "message": "All data has been cleared"}
    except Exception as e:
        logger.error(f"Error clearing data: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error clearing data: {str(e)}")

@app.post("/admin/embeddings/train/{upload_id}")
async def admin_train_embeddings(request: Request, upload_id: str):
    """Train embeddings for all messages from an import"""
    try:
        # Get the upload record
        upload = await app.db.uploads.find_one({"_id": ObjectId(upload_id)})
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")

        # Update status to TRAINING
        await app.db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {
                "$set": {
                    "status": "TRAINING",
                    "progress": "Starting training...",
                    "progress_percent": 0,
                    "training_started": datetime.utcnow(),
                    "error_message": None
                }
            }
        )

        # Start the training process in a background task
        import subprocess
        import sys
        import os

        # Run the train_embeddings.py script as a subprocess
        cmd = [sys.executable, os.path.join(os.path.dirname(__file__), "train_embeddings.py")]
        subprocess.Popen(cmd)

        return {"status": "success", "message": "Training started"}
    except Exception as e:
        logger.error(f"Error starting training: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error starting training: {str(e)}")

@app.post("/api/search-debug")
async def api_search_debug(
    request: Request,
    query: str = Form(...),
    limit: int = Form(50),
    hybrid_alpha: float = Form(0.5)
):
    """Debug endpoint for search"""
    try:
        # Create search service
        search_service = SearchService()

        # Perform search
        results = await search_service.search(query, limit, hybrid_alpha)

        # Return raw results
        return JSONResponse({
            "raw_results": results,
            "count": len(results),
            "query": query
        })
    except Exception as e:
        logger.error(f"Error in search: {str(e)}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/search-debug")
async def search_debug(q: str = "", hybrid_alpha: float = 0.5):
    """Debug endpoint for search results"""
    results = []
    if q:
        try:
            # Initialize search service if not already initialized
            if not hasattr(app, 'service') or not hasattr(app.service, 'search_service'):
                logger.error("Search service not initialized")
                raise HTTPException(status_code=500, detail="Search service not initialized")

            # Perform semantic search
            results = await app.service.search_service.search(
                query=q,
                limit=50,
                hybrid_alpha=hybrid_alpha
            )

            # Return the raw results for debugging
            return results
        except Exception as e:
            logging.error(f"Error in search_debug: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    return results

# Run the application
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
