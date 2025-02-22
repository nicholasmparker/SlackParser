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

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import our data module
from app import import_data

app = FastAPI()

# Get environment variables
FILE_STORAGE = os.getenv("FILE_STORAGE", "file_storage")
MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
MONGO_DB = os.getenv("MONGO_DB", "slack_data")

# Get base directory
BASE_DIR = Path(__file__).resolve().parent

# Setup static files and templates
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/files", StaticFiles(directory=FILE_STORAGE, html=True), name="files")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Add template filters
def timedelta_filter(value):
    """Format a timestamp as a human-readable time delta"""
    if not value:
        return ""
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        now = datetime.now(value.tzinfo)
        delta = now - value
        if delta.days > 365:
            years = delta.days // 365
            return f"{years} year{'s' if years != 1 else ''} ago"
        elif delta.days > 30:
            months = delta.days // 30
            return f"{months} month{'s' if months != 1 else ''} ago"
        elif delta.days > 0:
            return f"{delta.days} day{'s' if delta.days != 1 else ''} ago"
        elif delta.seconds > 3600:
            hours = delta.seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        elif delta.seconds > 60:
            minutes = delta.seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        else:
            return "just now"
    except Exception:
        return ""

templates.env.filters["timedelta"] = timedelta_filter

# Initialize embedding service
async def init_embedding_service():
    global embedding_service
    embedding_service = EmbeddingService()

# MongoDB connection
@app.on_event("startup")
async def startup_db_client():
    """Initialize MongoDB connection on startup"""
    try:
        app.mongodb_client = AsyncIOMotorClient(MONGO_URL)
        app.db = app.mongodb_client[MONGO_DB]
        logger.info(f"Connected to MongoDB at {MONGO_URL}")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        raise

@app.on_event("shutdown")
async def shutdown_db_client():
    """Close MongoDB connection on shutdown"""
    if hasattr(app, "mongodb_client"):
        app.mongodb_client.close()
        logger.info("Closed MongoDB connection")

# Ensure text search index exists
async def setup_indexes():
    await app.db.messages.create_index([("text", "text")])

@app.on_event("startup")
async def startup_event():
    """Initialize database connection and create indexes"""
    await setup_indexes()
    await init_embedding_service()

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
    
    # Get conversation metadata
    conversation = await app.db.conversations.find_one({"_id": conversation_id})
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
    
    # Get messages
    messages = await app.db.messages.find(
        query,
        {"score": {"$meta": "textScore"}, "ts": 1, "text": 1, "user": 1, "timestamp": 1, "files": 1, "reactions": 1} if q else None
    ).sort(sort).skip(skip).limit(page_size).to_list(length=page_size)
    
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
            "total_pages": total_pages
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
async def search(request: Request, q: str = ""):
    """Render search page or perform search"""
    if not q:
        return templates.TemplateResponse("search.html", {
            "request": request,
            "results": [],
            "query": ""
        })
    
    # Search messages
    results = await app.db.messages.find(
        {"$text": {"$search": q}},
        {"score": {"$meta": "textScore"}}
    ).sort([("score", {"$meta": "textScore"})]).to_list(length=50)
    
    # Get conversation details for each message
    for result in results:
        conversation = await app.db.conversations.find_one({"_id": result["conversation_id"]})
        result["conversation"] = conversation
    
    return templates.TemplateResponse("search.html", {
        "request": request,
        "results": results,
        "query": q
    })

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
        results = await embedding_service.search(
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
    uploads = await app.db.uploads.find().sort("created_at", -1).limit(10).to_list(10)
    
    # Convert ObjectId to string for each upload
    for upload in uploads:
        upload['_id'] = str(upload['_id'])
    
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "stats": stats,
            "uploads": uploads
        }
    )

@app.post("/admin/import/{upload_id}")
async def start_import(request: Request, upload_id: str):
    """Start importing a previously uploaded file"""
    try:
        db = request.app.db
        upload_id = ObjectId(upload_id)
        upload = await db.uploads.find_one({"_id": upload_id})
        
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")
            
        # Only allow starting import if file is in a valid state
        valid_states = ["UPLOADED", "cancelled", "error"]
        if upload["status"] not in valid_states:
            raise HTTPException(
                status_code=400, 
                detail=f"Cannot start import for file in state: {upload['status']}. Must be one of: {', '.join(valid_states)}"
            )
            
        # Update status to importing
        await db.uploads.update_one(
            {"_id": upload_id},
            {"$set": {"status": "IMPORTING", "error": None, "progress": None}}
        )
        
        # Start import in background
        asyncio.create_task(
            import_data.import_slack_export(
                db=db,
                file_path=Path(upload["file_path"]),
                upload_id=upload_id
            )
        )
        
        return {"status": "Import started"}
        
    except Exception as e:
        logger.exception("Error starting import")
        await db.uploads.update_one(
            {"_id": upload_id},
            {"$set": {"status": "error", "error": str(e)}}
        )
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/import/{upload_id}/status")
async def get_import_status(upload_id: str):
    """Get the status of an import"""
    try:
        upload = await app.db.uploads.find_one({"_id": ObjectId(upload_id)})
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")
        
        return {
            "status": upload.get("status", "unknown"),
            "progress": upload.get("progress", ""),
            "error": upload.get("error", "")
        }
    except Exception as e:
        logger.error(f"Error getting import status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def get_system_stats() -> Dict[str, int]:
    """Get system-wide statistics"""
    stats = {
        "total_messages": await app.db.messages.count_documents({}),
        "total_channels": await app.db.conversations.count_documents({"type": {"$in": ["Channel", "Private Channel"]}}),
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
        new_messages = await import_data.import_new_messages()
        
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
        
        if clear_messages:
            await app.db.messages.drop()
            print("Cleared messages")
            
        if clear_embeddings:
            # Clear Chroma collection
            await embedding_service.clear_collection()
            print("Cleared embeddings")
            
        if clear_uploads:
            await app.db.uploads.drop()
            # Clear upload directory
            upload_dir = Path("/data/uploads")
            if upload_dir.exists():
                for f in upload_dir.glob("*"):
                    if f.is_file():
                        f.unlink()
            # Clear extract directory
            extract_dir = Path("/data/extracts")
            if extract_dir.exists():
                for f in extract_dir.glob("*"):
                    if f.is_dir():
                        shutil.rmtree(f)
            print("Cleared uploads")
            
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

@app.post("/admin/cancel_import/{upload_id}")
async def cancel_import(request: Request, upload_id: str):
    """Cancel a stuck import"""
    try:
        # Update upload status to cancelled
        result = await app.db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {
                "$set": {
                    "status": "cancelled",
                    "updated_at": datetime.utcnow(),
                    "error": "Import cancelled by user"
                }
            }
        )
        
        if result.modified_count == 0:
            raise HTTPException(status_code=404, detail="Upload not found")
            
        return RedirectResponse(
            url="/admin",
            status_code=303
        )
    except Exception as e:
        logging.error(f"Cancel import failed: {str(e)}")
        return RedirectResponse(
            url=f"/admin?error=cancel_failed&message={str(e)}",
            status_code=303
        )

UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

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
                        {
                            "$set": {
                                "uploaded_size": total_size,
                                "size": total_size
                            }
                        }
                    )
                    last_update = total_size
                    logging.info(f"Uploaded {total_size} bytes")
        
        # Update final status
        await app.db.uploads.update_one(
            {"_id": upload_id},
            {
                "$set": {
                    "status": "UPLOADED",
                    "size": total_size,
                    "uploaded_size": total_size,
                    "updated_at": datetime.utcnow(),
                    "file_path": file_path
                }
            }
        )
        
        logging.info(f"Upload complete: {total_size} bytes")
        
        return JSONResponse({
            "id": str(upload_id),
            "status": "UPLOADED",
            "size": total_size
        })
        
    except Exception as e:
        logging.error(f"Upload error: {str(e)}", exc_info=True)
        # Try to clean up failed upload
        try:
            if 'file_path' in locals():
                os.unlink(file_path)
        except:
            pass
        try:
            if 'upload_id' in locals():
                await app.db.uploads.update_one(
                    {"_id": upload_id},
                    {"$set": {"status": "ERROR", "error": str(e)}}
                )
        except:
            pass
        raise HTTPException(status_code=500, detail=str(e))
