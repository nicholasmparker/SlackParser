"""Main application file for the SlackParser."""

import os
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path
from bson import ObjectId

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, BackgroundTasks, Body
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.cors import CORSMiddleware

# Import services
from app.services.main_service import MainService
from app.db.mongo import get_db, get_sync_db

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
templates = Jinja2Templates(directory="app/templates")

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
    app.db = await get_db()
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
        "index.html",
        {
            "request": request,
            "uploads": uploads,
            "channel_count": channel_count,
            "dm_count": dm_count,
            "message_count": message_count
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

@app.post("/extract/{upload_id}")
async def extract_upload(upload_id: str, background_tasks: BackgroundTasks):
    """Extract a ZIP file in the background."""
    try:
        # Get upload
        upload = await app.db.uploads.find_one({"_id": ObjectId(upload_id)})
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")
        
        # Start extraction in the background
        background_tasks.add_task(
            app.service.extraction_service.extract_with_progress,
            upload_id=upload_id,
            file_path=upload["file_path"]
        )
        
        return JSONResponse({"status": "EXTRACTING", "id": upload_id})
    except Exception as e:
        logger.error(f"Extract error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/import/{upload_id}")
async def import_upload(upload_id: str, background_tasks: BackgroundTasks):
    """Import a Slack export in the background."""
    try:
        # Start import in the background
        background_tasks.add_task(
            app.service.import_service.start_import_process,
            upload_id=upload_id
        )
        
        return JSONResponse({"status": "IMPORTING", "id": upload_id})
    except Exception as e:
        logger.error(f"Import error: {str(e)}", exc_info=True)
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

@app.get("/search")
async def search_page(request: Request, q: str = "", hybrid_alpha: float = 0.5):
    """Render the search page."""
    results = []
    if q:
        try:
            results = await app.service.search_service.search(
                query=q,
                limit=50,
                hybrid_alpha=hybrid_alpha
            )
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
                "user": r["user"],
                "timestamp": r["ts"],
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

@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, limit: int = 100, before: Optional[float] = None):
    """Get conversation by ID with messages."""
    try:
        # Get conversation
        conversation = await app.db.conversations.find_one({"channel_id": conversation_id})
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        # Build query for messages
        query = {"conversation_id": conversation_id}
        if before:
            query["ts"] = {"$lt": before}
        
        # Get messages
        messages = await app.db.messages.find(query).sort("ts", -1).limit(limit).to_list(length=limit)
        
        # Format response
        return JSONResponse({
            "conversation": {
                "id": conversation["channel_id"],
                "name": conversation.get("name", "Unknown"),
                "type": conversation.get("type", "unknown"),
                "created": conversation.get("created", ""),
                "topic": conversation.get("topic", ""),
                "purpose": conversation.get("purpose", "")
            },
            "messages": messages,
            "count": len(messages)
        })
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

# Run the application
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.new_main:app", host="0.0.0.0", port=8000, reload=True)
