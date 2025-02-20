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
        # Initialize ChromaDB
        self.chroma_client = chromadb.Client(Settings(
            persist_directory="chroma_data",
            is_persistent=True
        ))
        
        # Get or create collection
        collections = self.chroma_client.list_collections()
        if "slack_messages" in [c for c in collections]:
            self.collection = self.chroma_client.get_collection("slack_messages")
            logger.info("Using existing ChromaDB collection")
        else:
            # Delete any existing collections first
            for collection in collections:
                self.chroma_client.delete_collection(collection)
            
            # Create new collection
            self.collection = self.chroma_client.create_collection(
                name="slack_messages",
                metadata={"hnsw:space": "cosine"}
            )
            logger.info("Created new ChromaDB collection")
        
        # Ollama API endpoint
        self.ollama_url = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
        
        # Limit concurrent requests
        self.semaphore = asyncio.Semaphore(5)  # Max 5 concurrent requests

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
            async with httpx.AsyncClient() as client:
                logger.debug(f"Generating embedding for text: {text[:100]}")
                response = await client.post(
                    f"{self.ollama_url}/api/embeddings",
                    json={
                        "model": "nomic-embed-text",
                        "prompt": text
                    },
                    timeout=30.0
                )
                logger.debug(f"Got response: {response.status_code}")
                if response.status_code != 200:
                    logger.error(f"Error from Ollama: {response.text}")
                    return []
                    
                result = response.json()
                logger.debug(f"Response JSON: {result}")
                return result.get("embedding", [])

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
                self.collection.add(
                    embeddings=embeddings,
                    documents=texts,
                    metadatas=metadatas,
                    ids=ids
                )
                
                logger.info(f"Added batch of {len(batch)} messages ({i + len(batch)}/{total_messages})")
            except Exception as e:
                logger.error(f"Error processing batch {i//batch_size + 1}: {str(e)}", exc_info=True)
                raise

    async def semantic_search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for semantically similar messages"""
        # Generate query embedding
        query_embedding = await self.generate_embedding(query)
        
        # Search in ChromaDB
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=limit,
            include=["documents", "metadatas", "distances"]
        )
        
        # Format results
        messages = []
        for i in range(len(results["ids"][0])):
            messages.append({
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "similarity": 1 - results["distances"][0][i]  # Convert distance to similarity
            })
        
        return messages
    
    async def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for messages similar to the query"""
        try:
            # Generate embedding for query
            query_embedding = await self.generate_embedding(query)
            
            # Search in ChromaDB
            results = self.collection.query(
                query_embeddings=[query_embedding.tolist()],
                n_results=limit,
                include=["metadatas", "documents", "distances"]
            )
            
            # Format results
            formatted_results = []
            for i in range(len(results["ids"][0])):
                formatted_results.append({
                    "id": results["ids"][0][i],
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i]
                })
            
            return formatted_results
            
        except Exception as e:
            logger.error(f"Error in semantic search: {str(e)}", exc_info=True)
            return []

    async def delete_all(self):
        """Delete all data from the vector store"""
        try:
            # Delete the collection entirely
            self.chroma_client.delete_collection("slack_messages")
            # Recreate it
            self.collection = self.chroma_client.create_collection(
                name="slack_messages",
                metadata={"hnsw:space": "cosine"}
            )
        except Exception as e:
            logger.info(f"Error deleting collection: {str(e)}")
            # Collection might not exist, recreate it
            self.collection = self.chroma_client.create_collection(
                name="slack_messages",
                metadata={"hnsw:space": "cosine"}
            )
