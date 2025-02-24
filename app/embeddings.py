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
from app.config import CHROMA_PORT

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

class EmbeddingService:
    def __init__(self):
        """Initialize the embedding service"""
        chroma_host = os.getenv("CHROMA_HOST", "localhost")
        chroma_port = int(os.getenv("CHROMA_PORT", CHROMA_PORT))
        
        # Connect to Chroma
        self.client = chromadb.HttpClient(
            host=chroma_host,
            port=chroma_port,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        # Get or create collection with stable settings
        try:
            collections = self.client.list_collections()
            if "messages" in collections:
                self.collection = self.client.get_collection(name="messages")
                logger.info("Connected to existing messages collection")
                logger.info(f"Collection metadata: {self.collection.metadata}")
            else:
                logger.info("Creating new messages collection")
                self.collection = self.client.create_collection(
                    name="messages",
                    metadata={"hnsw:space": "cosine", "dimension": 768}
                )
        except Exception as e:
            logger.error(f"Error connecting to collection: {str(e)}")
            raise
        
        logger.info(f"Connected to Chroma at {chroma_host}:{chroma_port}")
        
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
        retry=tenacity.retry_if_exception_type((httpx.ConnectError, ValueError)),
        before_sleep=lambda retry_state: logger.warning(f"Retrying after error, attempt {retry_state.attempt_number}")
    )
    async def _make_ollama_request(self, text: str) -> List[float]:
        """Make a request to Ollama's embedding API"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.ollama_url}/v1/embeddings",
                    json={
                        "model": "nomic-embed-text",
                        "input": text
                    },
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
                logger.debug(f"Raw Ollama response: {data}")
                embeddings = data["data"][0]["embedding"]  # OpenAI format
                if not embeddings:
                    raise ValueError("Empty embeddings from Ollama")
                logger.info(f"Got embedding from Ollama with {len(embeddings)} dimensions")
                return embeddings
        except Exception as e:
            logger.error(f"Error making Ollama request: {str(e)}")
            raise

    async def generate_embedding(self, text: str) -> np.ndarray:
        """Generate embeddings using Ollama's nomic-embed-text model"""
        try:
            if not text or text.isspace():
                logger.warning("Empty or whitespace-only text, returning zero vector")
                return np.zeros(768, dtype=np.float32)
            
            embedding = await self._make_ollama_request(text)
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
        
        # Process messages in chunks to avoid memory issues
        chunk_size = 1000  # Process 1000 messages at a time
        for chunk_start in range(0, total_messages, chunk_size):
            chunk_end = min(chunk_start + chunk_size, total_messages)
            chunk = messages[chunk_start:chunk_end]
            logger.info(f"Processing chunk {chunk_start}-{chunk_end} of {total_messages} messages")
            
            for i in range(0, len(chunk), batch_size):
                batch = chunk[i:i + batch_size]
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
                        "channel": msg.get("channel", ""),
                        "user": msg.get("user", ""),
                        "thread_ts": msg.get("thread_ts", ""),
                        "timestamp": float(msg.get("ts", 0)) if msg.get("ts") else 0,  # Convert to float
                        "text": msg.get("text", ""),
                    } for msg in batch]
                    
                    # Add to ChromaDB
                    await self.add_embeddings(embeddings, ids, metadatas, texts)
                    
                    # Log progress
                    progress = min((chunk_start + i + batch_size) / total_messages * 100, 100)
                    logger.info(f"Progress: {progress:.1f}% ({chunk_start + i + len(batch)}/{total_messages} messages)")
                    
                except Exception as e:
                    logger.error(f"Error processing batch: {str(e)}", exc_info=True)
    
    async def add_embeddings(self, embeddings, ids, metadatas=None, documents=None):
        """Add embeddings to Chroma"""
        if not embeddings:
            return
            
        # Ensure ids are strings
        ids = [str(id) for id in ids]
        
        try:
            self.collection.add(
                embeddings=embeddings,
                documents=documents,
                ids=ids,
                metadatas=metadatas
            )
            logger.info(f"Added {len(embeddings)} embeddings to Chroma")
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
    
    async def search(self, query: str, limit: int = 10, hybrid_alpha: float = 0.5) -> List[Dict[str, Any]]:
        """Search for messages using hybrid semantic + keyword search
        
        Args:
            query: Search query
            limit: Maximum number of results to return
            hybrid_alpha: Balance between semantic (alpha) and keyword (1-alpha) search
            
        Returns:
            List of results with text, metadata, and similarity score
        """
        try:
            logger.info(f"Searching for '{query}' with limit={limit}, hybrid_alpha={hybrid_alpha}")
            
            # Get collection count
            count = self.collection.count()
            logger.info(f"Collection has {count} documents")
            
            # Format and combine results
            all_results = []
            
            # Do semantic search if hybrid_alpha > 0
            if hybrid_alpha > 0:
                # Get query embedding for semantic search
                query_embedding = await self.generate_embedding(query)
                logger.info(f"Generated query embedding with {len(query_embedding)} dimensions")
                
                # Get more results than needed since we'll combine them
                expanded_limit = min(limit * 2, count)
                
                # Semantic search
                semantic_results = self.collection.query(
                    query_embeddings=[query_embedding.tolist()],
                    n_results=expanded_limit,
                    include=['documents', 'metadatas', 'distances']
                )
                logger.info(f"Got {len(semantic_results['ids'][0])} semantic results from Chroma")
                
                # Add semantic results
                if semantic_results["ids"] and semantic_results["ids"][0]:
                    for i in range(len(semantic_results["ids"][0])):
                        # Skip test messages
                        if semantic_results["documents"][0][i].strip().lower() == "test message":
                            continue
                            
                        all_results.append({
                            "text": semantic_results["documents"][0][i],
                            "metadata": semantic_results["metadatas"][0][i],
                            "similarity": hybrid_alpha * (1 - semantic_results["distances"][0][i]),  # Weight semantic score by alpha
                            "keyword_match": False
                        })
            
            # Do keyword search if hybrid_alpha < 1
            if hybrid_alpha < 1:
                # Get all documents to search through
                all_docs = self.collection.get(
                    include=['documents', 'metadatas']
                )
                
                # Simple substring search
                query_lower = query.lower()
                for i in range(len(all_docs["documents"])):
                    text = all_docs["documents"][i].lower()
                    if query_lower in text:
                        # Check if this result is already in all_results
                        if not any(r.get("text") == all_docs["documents"][i] for r in all_results):
                            all_results.append({
                                "text": all_docs["documents"][i],
                                "metadata": all_docs["metadatas"][i],
                                "similarity": (1 - hybrid_alpha),  # Full score for exact matches
                                "keyword_match": True
                            })
            
            # Sort by combined score and take top results
            all_results.sort(key=lambda x: x["similarity"], reverse=True)
            return all_results[:limit]
            
        except Exception as e:
            logger.error(f"Error searching: {str(e)}")
            raise
    
    async def delete_all(self):
        """Delete all embeddings from the collection"""
        logger.info("Clearing existing embeddings...")
        try:
            self.client.reset()
            logger.info("Reset Chroma database")
            
            # Create new collection with correct dimensions
            self.collection = self.client.create_collection(
                name="messages",
                metadata={"hnsw:space": "cosine", "dimension": 768}
            )
            logger.info("Created new collection with correct dimensions")
            
            # Add test embedding to verify dimensions
            try:
                test_embedding = await self.generate_embedding("test")
                await self.add_embeddings([test_embedding], ["test"], [{"test": True}], ["test"])
                logger.info("Added test embedding successfully")
            except Exception as e:
                logger.error(f"Failed to add test embedding: {str(e)}")
                raise
        except Exception as e:
            logger.error(f"Error resetting collection: {str(e)}")
            raise
    
    async def clear_collection(self):
        """Clear all embeddings from the collection"""
        try:
            # Delete the collection
            self.client.delete_collection(name="messages")
            
            # Recreate the collection
            self.collection = self.client.create_collection(
                name="messages",
                metadata={"hnsw:space": "cosine", "dimension": 768}
            )
            logger.info("Cleared all embeddings from collection")
        except Exception as e:
            logger.error(f"Error clearing collection: {str(e)}")
            raise

    async def reset_collection(self) -> None:
        """Reset the collection to ensure correct embedding dimensions"""
        try:
            # Reset the collection
            self.client.reset()
            logger.info("Reset Chroma database")
            
            # Create new collection with correct dimensions
            self.collection = self.client.create_collection(
                name="messages",
                metadata={"hnsw:space": "cosine", "dimension": 768}
            )
            logger.info("Created new collection with correct dimensions")
            
            # Add test embedding to verify dimensions
            try:
                test_embedding = await self.generate_embedding("test")
                await self.add_embeddings([test_embedding], ["test"], [{"test": True}], ["test"])
                logger.info("Added test embedding successfully")
            except Exception as e:
                logger.error(f"Failed to add test embedding: {str(e)}")
                raise
        except Exception as e:
            logger.error(f"Error resetting collection: {str(e)}")
            raise
