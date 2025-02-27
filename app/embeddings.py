"""Service for managing embeddings and semantic search."""

import os
import httpx
import chromadb
from chromadb.config import Settings
import logging
import numpy as np
import tenacity
import re
import traceback
from datetime import datetime
from urllib.parse import urlparse
from typing import List, Dict, Any, Optional
from app.config import CHROMA_PORT, CHROMA_HOST

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

class EmbeddingService:
    def __init__(self):
        """Initialize the embedding service"""
        self.chroma_client = None
        self.collection = None
        self.collection_name = "messages"
        self.metadata = {
            "dimension": 768,
            "hnsw:space": "cosine"
        }

    def initialize(self):
        """Initialize the Chroma client and collection"""
        try:
            # Initialize ChromaDB client
            self.chroma_client = chromadb.HttpClient(
                host=CHROMA_HOST,
                port=CHROMA_PORT,
                settings=Settings(anonymized_telemetry=True),
            )

            # Get or create collection
            try:
                self.collection = self.chroma_client.get_collection(
                    name=self.collection_name,
                )
                logger.info(f"Connected to existing {self.collection_name} collection")
                logger.info(f"Collection metadata: {self.collection.metadata}")
            except Exception:
                self.collection = self.chroma_client.create_collection(
                    name=self.collection_name,
                    metadata=self.metadata,
                )
                logger.info(f"Created new {self.collection_name} collection")

            logger.info("Connected to Chroma")

        except Exception as e:
            logger.error(f"Error initializing Chroma client: {str(e)}")
            raise e

        # Initialize Ollama client
        self.ollama_url = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")

        # Ollama API endpoint
        self.semaphore = 5  # Max 5 concurrent requests

    def init(self):
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

    def _prepare_message_text(self, message: Dict[str, Any]) -> str:
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
    def _make_ollama_request(self, text: str) -> List[float]:
        """Make a request to Ollama's embedding API"""
        try:
            with httpx.Client() as client:
                response = client.post(
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

    def generate_embedding(self, text: str) -> np.ndarray:
        """Generate embeddings using Ollama's nomic-embed-text model"""
        try:
            if not text or text.isspace():
                logger.warning("Empty or whitespace-only text, returning zero vector")
                return np.zeros(768, dtype=np.float32)

            embedding = self._make_ollama_request(text)
            logger.debug(f"Got embedding with {len(embedding)} dimensions")
            return np.array(embedding, dtype=np.float32)
        except Exception as e:
            logger.error(f"Error generating embedding: {str(e)}", exc_info=True)
            return np.zeros(768, dtype=np.float32)  # Return zeros with correct dimension

    def add_messages(self, messages: List[Dict]):
        """Add messages to ChromaDB"""
        try:
            total_messages = len(messages)
            logger.info(f"Processing {total_messages} messages")

            # Process messages
            for message in messages:
                if not isinstance(message, dict) or "text" not in message:
                    logger.warning(f"Skipping invalid message: {message}")
                    continue

                text = message.get("text", "").strip()
                if not text:
                    logger.warning("Skipping empty message text")
                    continue

                # Add thread context if available
                thread_context = self._get_thread_context(message)
                if thread_context:
                    text = f"{text}\n\nThread Context:\n{thread_context}"

                # Clean and prepare text
                text = self._clean_text(text)
                if not text:
                    logger.warning("Skipping message after cleaning")
                    continue

                # Generate embedding
                embedding = self.generate_embedding(text)

                # Convert NumPy array to list for ChromaDB
                if isinstance(embedding, np.ndarray):
                    embedding = embedding.tolist()

                # Add to ChromaDB
                metadata = {
                    "conversation_id": str(message["conversation_id"]),
                    "timestamp": str(message.get("ts", "")),
                    "thread_ts": str(message.get("thread_ts", "")),
                    "user": str(message.get("user", "")),
                }

                self.collection.add(
                    embeddings=[embedding],
                    documents=[text],
                    ids=[str(message["_id"])],
                    metadatas=[metadata]
                )

                logger.info(f"Added message ({message['_id']})")

        except Exception as e:
            logger.error(f"Error adding messages: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    def add_embeddings(self, embeddings, ids, metadatas=None, documents=None):
        """Add embeddings to Chroma"""
        if not embeddings:
            return

        # Ensure ids are strings
        ids = [str(id) for id in ids]

        # Convert NumPy arrays to lists if necessary
        processed_embeddings = []
        for emb in embeddings:
            if isinstance(emb, np.ndarray):
                processed_embeddings.append(emb.tolist())
            else:
                processed_embeddings.append(emb)

        # Convert metadata values to strings
        if metadatas:
            processed_metadatas = []
            for meta in metadatas:
                if meta:
                    processed_meta = {}
                    for key, value in meta.items():
                        processed_meta[key] = str(value)
                    processed_metadatas.append(processed_meta)
                else:
                    processed_metadatas.append(meta)
        else:
            processed_metadatas = metadatas

        try:
            self.collection.add(
                embeddings=processed_embeddings,
                documents=documents,
                ids=ids,
                metadatas=processed_metadatas
            )
            logger.info(f"Added {len(processed_embeddings)} embeddings to Chroma")
        except Exception as e:
            logger.error(f"Error adding embeddings: {str(e)}")
            raise

    def semantic_search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for semantically similar messages"""
        # Generate query embedding
        query_embedding = self.generate_embedding(query)

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

    def search(self, query: str, limit: int = 10, hybrid_alpha: float = 0.5) -> List[Dict[str, Any]]:
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
                query_embedding = self.generate_embedding(query)
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

                        # Debug log metadata fields
                        metadata = semantic_results["metadatas"][0][i]
                        logger.info(f"Metadata fields: {list(metadata.keys())}")

                        all_results.append({
                            "text": semantic_results["documents"][0][i],
                            "metadata": metadata,
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

    def clear_all_embeddings(self):
        """Clear all embeddings from the collection"""
        try:
            # Delete the collection
            self.chroma_client.delete_collection(name="messages")

            # Recreate the collection
            self.collection = self.chroma_client.create_collection(
                name="messages",
                metadata={"dimension": 768, "hnsw:space": "cosine"}
            )
            logger.info("Cleared all embeddings from collection")
        except Exception as e:
            logger.error(f"Error clearing embeddings: {str(e)}")
            # Create new collection with correct dimensions
            self.collection = self.chroma_client.create_collection(
                name="messages",
                metadata={"dimension": 768, "hnsw:space": "cosine"}
            )
            logger.info("Created new collection with correct dimensions")

    def reset_collection(self) -> None:
        """Reset the collection to ensure correct embedding dimensions"""
        try:
            # Reset the collection
            self.chroma_client.reset()
            logger.info("Reset Chroma database")

            # Create new collection with correct dimensions
            self.collection = self.chroma_client.create_collection(
                name="messages",
                metadata={"dimension": 768, "hnsw:space": "cosine"}
            )
            logger.info("Created new collection with correct dimensions")

            # Add test embedding to verify dimensions
            try:
                test_embedding = self.generate_embedding("test")
                self.add_embeddings([test_embedding], ["test"], [{"test": True}], ["test"])
                logger.info("Added test embedding successfully")
            except Exception as e:
                logger.error(f"Failed to add test embedding: {str(e)}")
                raise
        except Exception as e:
            logger.error(f"Error resetting collection: {str(e)}")
            raise
