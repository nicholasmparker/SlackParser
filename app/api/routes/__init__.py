from fastapi import APIRouter

from app.api.routes import admin, conversations, search, uploads, imports

router = APIRouter()
router.include_router(admin.router, prefix="/admin", tags=["admin"])
router.include_router(conversations.router, prefix="", tags=["conversations"])
router.include_router(search.router, prefix="", tags=["search"])
router.include_router(uploads.router, prefix="", tags=["uploads"])
router.include_router(imports.router, prefix="", tags=["imports"])
