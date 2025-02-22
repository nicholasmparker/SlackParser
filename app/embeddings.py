import os
import httpx
import chromadb
from chromadb.config import Settings
import asyncio
from typing import List, Dict, Any, Optional
import logging
import numpy as np
import tenacity
import re
from datetime import datetime
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

class EmbeddingService:
    def __init__(self):
        """Initialize the embedding service"""
        chroma_host = os.getenv("CHROMA_HOST", "localhost")
        chroma_port = int(os.getenv("CHROMA_PORT", "8000"))
        
        # Connect to Chroma
        self.client = chromadb.HttpClient(
            host=chroma_host,
            port=chroma_port,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        # Create or get collection
        self.collection = self.client.get_or_create_collection(
            name="messages",
            metadata={"hnsw:space": "cosine"}
        )
        
        logging.info(f"Connected to Chroma at {chroma_host}:{chroma_port}")
        
        # Initialize Ollama client
        self.ollama_url = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
        
        # Ollama API endpoint
        self.semaphore = asyncio.Semaphore(5)  # Max 5 concurrent requests

    async def init(self):
        """Initialize ChromaDB and other resources"""
        pass  # No initialization needed for Chroma container

    def _clean_text(self, text: str) -> str:
        """Clean and normalize text for better embeddings"""
        if not text:
            return ""
            
        # Replace common Slack formatting
        text = re.sub(r'<@\w+>', '@user', text)  # Replace user mentions
        text = re.sub(r'<#\w+\|([^>]+)>', r'#\1', text)  # Replace channel mentions
        text = re.sub(r'<(https?://[^|>]+)\|([^>]+)>', r'\2 (\1)', text)  # Clean URLs with titles
        text = re.sub(r'<(https?://[^>]+)>', r'\1', text)  # Clean bare URLs
        
        # Handle code blocks
        text = re.sub(r'```[\s\S]*?```', '[code block]', text)  # Replace code blocks
        text = re.sub(r'`[^`]+`', '[code]', text)  # Replace inline code
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text

    def _extract_urls(self, text: str) -> List[str]:
        """Extract URLs from text"""
        return re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text)

    def _get_thread_context(self, message: Dict[str, Any]) -> Optional[str]:
        """Get thread context if available"""
        thread_ts = message.get("thread_ts")
        parent_text = message.get("parent_message", {}).get("text", "")
        if thread_ts and parent_text:
            return f"Thread context: {self._clean_text(parent_text)}\nReply: "
        return None

    def _format_reactions(self, message: Dict[str, Any]) -> Optional[str]:
        """Format reactions into meaningful text"""
        reactions = message.get("reactions", [])
        if reactions:
            reaction_texts = []
            for reaction in reactions:
                count = reaction.get("count", 0)
                users = len(reaction.get("users", []))
                name = reaction.get("name", "")
                if count > 1:
                    reaction_texts.append(f"{name} ({count} times)")
            if reaction_texts:
                return f"\nReactions: {', '.join(reaction_texts)}"
        return None

    async def _prepare_message_text(self, message: Dict[str, Any]) -> str:
        """Prepare message text for embedding by combining various contexts"""
        parts = []
        
        # Add thread context if available
        thread_context = self._get_thread_context(message)
        if thread_context:
            parts.append(thread_context)
        
        # Add main message text
        text = message.get("text", "")
        cleaned_text = self._clean_text(text)
        if cleaned_text:
            parts.append(cleaned_text)
        
        # Add reactions if present
        reactions = self._format_reactions(message)
        if reactions:
            parts.append(reactions)
        
        # Add file context if present
        files = message.get("files", [])
        if files:
            file_names = [f.get("name", "unnamed") for f in files]
            parts.append(f"\nAttached files: {', '.join(file_names)}")
        
        return " ".join(parts)

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_exponential(multiplier=1, min=1, max=10),
        retry=tenacity.retry_if_exception_type(httpx.ConnectError),
        before_sleep=lambda retry_state: logger.warning(f"Retrying after error, attempt {retry_state.attempt_number}")
    )
    async def _make_ollama_request(self, text: str) -> List[float]:
        """Make a request to Ollama with retry logic"""
        async with self.semaphore:  # Limit concurrent requests
            async with httpx.AsyncClient(base_url=self.ollama_url) as client:
                logger.debug(f"Generating embedding for text: {text[:100]}")
                response = await client.post(
                    "/api/embeddings",
                    json={
                        "model": "nomic-embed-text",
                        "prompt": text
                    },
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()["embedding"]

    async def generate_embedding(self, text: str) -> np.ndarray:
        """Generate embeddings using Ollama's nomic-embed-text model"""
        try:
            embedding = await self._make_ollama_request(text)
            if not embedding:
                logger.error("Got empty embedding from Ollama")
                return np.zeros(768, dtype=np.float32)  # Return zeros with correct dimension
            logger.debug(f"Got embedding with {len(embedding)} dimensions")
            return np.array(embedding, dtype=np.float32)
        except Exception as e:
            logger.error(f"Error generating embedding: {str(e)}", exc_info=True)
            return np.zeros(768, dtype=np.float32)  # Return zeros with correct dimension

    async def add_messages(self, messages: List[Dict[str, Any]], batch_size: int = 50):
        """Add messages to ChromaDB with their embeddings in batches"""
        if not messages:
            return
            
        total_messages = len(messages)
        logger.info(f"Processing {total_messages} messages in batches of {batch_size}")
        
        for i in range(0, total_messages, batch_size):
            batch = messages[i:i + batch_size]
            try:
                # Prepare texts with context
                texts = await asyncio.gather(*[
                    self._prepare_message_text(msg) 
                    for msg in batch
                ])
                
                # Generate embeddings in parallel
                embeddings = await asyncio.gather(*[
                    self.generate_embedding(text) 
                    for text in texts
                ])
                
                # Prepare data for ChromaDB
                ids = [str(msg["_id"]) for msg in batch]
                metadatas = [{
                    "user": msg.get("user", "unknown"),
                    "conversation_id": msg.get("conversation_id", "unknown"),
                    "channel_name": msg.get("channel_name", "unknown"),
                    "timestamp": msg.get("timestamp", "").isoformat() if msg.get("timestamp") else "",
                    "ts": str(msg.get("ts", "")),
                    "is_thread_reply": bool(msg.get("thread_ts")),
                    "has_files": bool(msg.get("files")),
                    "reaction_count": sum(r.get("count", 0) for r in msg.get("reactions", [])),
                    "reply_count": msg.get("reply_count", 0)
                } for msg in batch]
                
                # Add to ChromaDB
                await self.add_embeddings(texts, ids, metadatas)
                
                logger.info(f"Added batch of {len(batch)} messages ({i + len(batch)}/{total_messages})")
            except Exception as e:
                logger.error(f"Error processing batch {i//batch_size + 1}: {str(e)}", exc_info=True)
                raise

    async def add_embeddings(self, texts, ids, metadatas=None):
        """Add embeddings to Chroma"""
        if not texts:
            return
            
        # Ensure ids are strings
        ids = [str(id) for id in ids]
        
        try:
            self.collection.add(
                documents=texts,
                ids=ids,
                metadatas=metadatas
            )
            logger.info(f"Added {len(texts)} embeddings to Chroma")
        except Exception as e:
            logger.error(f"Error adding embeddings: {str(e)}")
            raise
    
    async def semantic_search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for semantically similar messages"""
        # Generate query embedding
        query_embedding = await self.generate_embedding(query)
        
        # Search in ChromaDB
        results = self.collection.query(
            query_embeddings=[query_embedding.tolist()],  # Convert numpy array to list
            n_results=limit,
            include=["documents", "metadatas", "distances"]
        )
        
        # Format results
        messages = []
        if results["ids"] and results["ids"][0]:  # Check if we have results
            for i in range(len(results["ids"][0])):
                messages.append({
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "similarity": 1 - results["distances"][0][i]  # Convert distance to similarity
                })
        
        return messages
    
    async def search(self, query: str, limit: int = 10, hybrid_alpha: float = 0.5, 
                    filter_channels: Optional[List[str]] = None,
                    filter_users: Optional[List[str]] = None,
                    filter_has_files: Optional[bool] = None,
                    filter_has_reactions: Optional[bool] = None,
                    filter_in_thread: Optional[bool] = None,
                    filter_date_range: Optional[tuple[datetime, datetime]] = None) -> List[Dict[str, Any]]:
        """Search for messages using hybrid semantic + keyword search with filtering"""
        try:
            # Build where clause for filtering
            where = {}
            
            if filter_channels:
                where["conversation_id"] = {"$in": filter_channels}  # Use conversation_id instead of channel_name
            if filter_users:
                where["user"] = {"$in": filter_users}
            if filter_has_files is not None:
                where["has_files"] = filter_has_files
            if filter_has_reactions is not None:
                where["reaction_count"] = {"$gt": 0} if filter_has_reactions else 0
            if filter_in_thread is not None:
                where["is_thread_reply"] = filter_in_thread
            if filter_date_range:
                start, end = filter_date_range
                where["timestamp"] = {
                    "$gte": start.isoformat(),
                    "$lte": end.isoformat()
                }
            
            logger.info(f"Searching with query: {query}")
            logger.info(f"Where clause: {where}")
            
            # Generate embedding for semantic search
            query_embedding = await self.generate_embedding(query)
            logger.info(f"Generated embedding with shape: {query_embedding.shape}")
            
            # Get more results than needed for hybrid search
            search_limit = min(limit * 4, 100)  # Get more results to combine
            
            # Do semantic search
            semantic_results = self.collection.query(
                query_embeddings=[query_embedding.tolist()],
                n_results=search_limit,
                include=["metadatas", "documents", "distances"],
                where=where or None
            )
            
            # Do keyword search if hybrid_alpha > 0
            keyword_results = None
            if hybrid_alpha > 0:
                try:
                    # Use query directly for keyword search
                    keyword_results = self.collection.query(
                        query_embeddings=None,
                        query_texts=[query],
                        n_results=search_limit,
                        include=["metadatas", "documents", "distances"],
                        where=where or None
                    )
                except Exception as e:
                    logger.warning(f"Keyword search failed: {str(e)}")
            
            # Combine results with hybrid scoring
            results_dict = {}  # id -> result
            
            # Add semantic results
            if semantic_results["ids"] and semantic_results["ids"][0]:
                semantic_weight = 1 - hybrid_alpha  # When alpha is 0, semantic gets full weight
                
                # Get min and max distances for normalization
                distances = semantic_results["distances"][0]
                min_distance = min(distances)
                max_distance = max(distances)
                distance_range = max_distance - min_distance if max_distance > min_distance else 1.0
                
                for i in range(len(semantic_results["ids"][0])):
                    result_id = semantic_results["ids"][0][i]
                    metadata = semantic_results["metadatas"][0][i]
                    text = semantic_results["documents"][0][i]
                    
                    # Normalize distance to similarity score (0-1)
                    distance = semantic_results["distances"][0][i]
                    semantic_score = 1 - ((distance - min_distance) / distance_range)
                    
                    results_dict[result_id] = {
                        "_id": metadata.get("_id", result_id),
                        "conversation_id": metadata.get("conversation_id"),
                        "text": text,
                        "user": metadata.get("user"),
                        "timestamp": metadata.get("timestamp"),
                        "thread_ts": metadata.get("thread_ts"),
                        "parent_message": metadata.get("parent_message"),
                        "reactions": metadata.get("reactions", []),
                        "files": metadata.get("files", []),
                        "semantic_score": semantic_score,
                        "keyword_score": 0.0,
                        "score": semantic_score * semantic_weight
                    }
            
            # Add keyword results
            if keyword_results and keyword_results["ids"] and keyword_results["ids"][0]:
                keyword_weight = hybrid_alpha  # When alpha is 1, keyword gets full weight
                
                # Get min and max distances for normalization
                distances = keyword_results["distances"][0]
                min_distance = min(distances)
                max_distance = max(distances)
                distance_range = max_distance - min_distance if max_distance > min_distance else 1.0
                
                for i in range(len(keyword_results["ids"][0])):
                    result_id = keyword_results["ids"][0][i]
                    metadata = keyword_results["metadatas"][0][i]
                    text = keyword_results["documents"][0][i]
                    
                    # Normalize distance to similarity score (0-1)
                    distance = keyword_results["distances"][0][i]
                    keyword_score = 1 - ((distance - min_distance) / distance_range)
                    
                    if result_id in results_dict:
                        # Update existing result with keyword score
                        results_dict[result_id]["keyword_score"] = keyword_score
                        results_dict[result_id]["score"] += keyword_score * keyword_weight
                    else:
                        # Add new result
                        results_dict[result_id] = {
                            "_id": metadata.get("_id", result_id),
                            "conversation_id": metadata.get("conversation_id"),
                            "text": text,
                            "user": metadata.get("user"),
                            "timestamp": metadata.get("timestamp"),
                            "thread_ts": metadata.get("thread_ts"),
                            "parent_message": metadata.get("parent_message"),
                            "reactions": metadata.get("reactions", []),
                            "files": metadata.get("files", []),
                            "semantic_score": 0.0,
                            "keyword_score": keyword_score,
                            "score": keyword_score * keyword_weight
                        }
            
            # Sort by total score and return top results
            sorted_results = sorted(results_dict.values(), key=lambda x: x["score"], reverse=True)[:limit]
            
            # Log some info about the results
            logger.info(f"Got {len(sorted_results)} total results")
            if sorted_results:
                top_result = sorted_results[0]
                logger.info(f"Top result: {top_result['text'][:100]}")
                logger.info(f"Top result scores:")
                logger.info(f"  - Total score: {top_result['score']:.3f}")
                logger.info(f"  - Semantic score: {top_result['semantic_score']:.3f} (weight: {1-hybrid_alpha:.2f})")
                logger.info(f"  - Keyword score: {top_result['keyword_score']:.3f} (weight: {hybrid_alpha:.2f})")
                
                # Log all results with their scores
                logger.info("\nAll results:")
                for i, result in enumerate(sorted_results[:5]):  # Show top 5
                    logger.info(f"\nResult {i+1}:")
                    logger.info(f"Text: {result['text'][:100]}")
                    logger.info(f"Total score: {result['score']:.3f}")
                    logger.info(f"Semantic: {result['semantic_score']:.3f}, Keyword: {result['keyword_score']:.3f}")
            
            return sorted_results
            
        except Exception as e:
            logger.error(f"Search error: {str(e)}", exc_info=True)
            raise

    async def delete_all(self):
        """Delete all data from the vector store"""
        try:
            # Delete the collection entirely
            self.client.reset()
            logger.info("Reset Chroma collection")
        except Exception as e:
            logger.info(f"Error deleting collection: {str(e)}")
            # Collection might not exist, recreate it
            self.collection = self.client.get_or_create_collection(
                name="messages",
                metadata={"hnsw:space": "cosine"}
            )

    async def clear_collection(self):
        """Clear all embeddings from the collection"""
        self.collection.delete(where={})
        logger.info("Cleared all embeddings")
