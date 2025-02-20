import os
import httpx
import chromadb
from chromadb.config import Settings
import asyncio
from typing import List, Dict, Any
import logging
import numpy as np
import tenacity

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
    
    async def add_messages(self, messages: List[Dict[str, Any]]):
        """Add messages to ChromaDB with their embeddings"""
        if not messages:
            return
            
        try:
            # Generate embeddings in parallel
            embeddings = await asyncio.gather(*[
                self.generate_embedding(str(msg.get("text", ""))) 
                for msg in messages
            ])
            
            # Prepare data for ChromaDB
            ids = [str(msg["_id"]) for msg in messages]
            texts = [str(msg.get("text", "")) for msg in messages]
            metadatas = [{
                "user": msg.get("user", "unknown"),
                "conversation_id": msg.get("conversation_id", "unknown"),
                "timestamp": msg.get("timestamp", "").isoformat() if msg.get("timestamp") else "",
                "ts": str(msg.get("ts", ""))
            } for msg in messages]
            
            # Add to ChromaDB
            self.collection.add(
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
                ids=ids
            )
            
            logger.info(f"Added {len(messages)} messages to vector store")
        except Exception as e:
            logger.error(f"Error adding messages: {str(e)}", exc_info=True)
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
