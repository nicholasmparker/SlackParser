"""Main service for the SlackParser application."""

import logging
from typing import Any, Dict, Optional

from app.services.extraction_service import ExtractionService
from app.services.import_service import ImportService
from app.services.search_service import SearchService
from app.services.upload_service import UploadService

logger = logging.getLogger(__name__)

class MainService:
    """Main service for the SlackParser application."""
    
    def __init__(self, db=None, sync_db=None):
        """Initialize the main service.
        
        Args:
            db: Async MongoDB database instance
            sync_db: Sync MongoDB database instance
        """
        self.db = db
        self.sync_db = sync_db
        
        # Initialize services
        self._extraction_service = None
        self._import_service = None
        self._search_service = None
        self._upload_service = None
    
    @property
    def extraction_service(self) -> ExtractionService:
        """Get the extraction service.
        
        Returns:
            ExtractionService instance
        """
        if not self._extraction_service:
            self._extraction_service = ExtractionService(db=self.db, sync_db=self.sync_db)
        return self._extraction_service
    
    @property
    def import_service(self) -> ImportService:
        """Get the import service.
        
        Returns:
            ImportService instance
        """
        if not self._import_service:
            self._import_service = ImportService(db=self.db, sync_db=self.sync_db)
        return self._import_service
    
    @property
    def search_service(self) -> SearchService:
        """Get the search service.
        
        Returns:
            SearchService instance
        """
        if not self._search_service:
            self._search_service = SearchService(db=self.db, sync_db=self.sync_db)
        return self._search_service
    
    @property
    def upload_service(self) -> UploadService:
        """Get the upload service.
        
        Returns:
            UploadService instance
        """
        if not self._upload_service:
            self._upload_service = UploadService(db=self.db, sync_db=self.sync_db)
        return self._upload_service
