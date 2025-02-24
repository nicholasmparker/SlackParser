import asyncio
from .embeddings import EmbeddingService

async def test():
    service = EmbeddingService()
    embedding = await service.generate_embedding("test message")
    print("Got embedding:", embedding)
    
    # Try adding a message
    await service.add_messages([{
        "_id": "test_id",
        "text": "test message",
        "user": "test_user",
        "conversation_id": "test_conv",
        "timestamp": "2023-01-01",
        "ts": "123456"
    }])
    print("Added test message")
    
    # Try searching
    results = await service.semantic_search("test")
    print("Search results:", results)

if __name__ == "__main__":
    asyncio.run(test())
