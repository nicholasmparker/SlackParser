import asyncio
from .embeddings import EmbeddingService

async def main():
    embedding_service = EmbeddingService()
    
    # Add a few test messages with semantic relationships
    messages = [
        {
            "_id": "1",
            "text": "The quarterly financial report shows strong revenue growth",
            "channel": "finance",
            "user": "alice",
            "timestamp": "2023-01-01",
            "thread_ts": ""
        },
        {
            "_id": "2", 
            "text": "Our profits increased by 25% this quarter",
            "channel": "finance",
            "user": "bob",
            "timestamp": "2023-01-02",
            "thread_ts": ""
        },
        {
            "_id": "3",
            "text": "The new marketing campaign launched today",
            "channel": "marketing",
            "user": "carol",
            "timestamp": "2023-01-03",
            "thread_ts": ""
        },
        {
            "_id": "4",
            "text": "I'm feeling really down today, everything is going wrong",
            "channel": "random",
            "user": "dave",
            "timestamp": "2023-01-04",
            "thread_ts": ""
        },
        {
            "_id": "5",
            "text": "Just got some amazing news! So excited to share with everyone!",
            "channel": "random",
            "user": "emma",
            "timestamp": "2023-01-05",
            "thread_ts": ""
        },
        {
            "_id": "6",
            "text": "This has been such a frustrating and disappointing day",
            "channel": "random",
            "user": "frank",
            "timestamp": "2023-01-06",
            "thread_ts": ""
        },
        {
            "_id": "7",
            "text": "Celebrating a huge milestone today! Couldn't be happier!",
            "channel": "random",
            "user": "grace",
            "timestamp": "2023-01-07",
            "thread_ts": ""
        }
    ]
    
    print("\nAdding test messages...")
    await embedding_service.add_messages(messages)
    
    # Try semantic searches that should match without keyword overlap
    queries = [
        "How is our business performance?",  # Should match financial messages
        "What's happening with company earnings?",  # Should match profit/revenue messages
        "Updates about our advertising efforts?"  # Should match marketing message
    ]
    
    for query in queries:
        print(f"\nSearching for: {query}")
        results = await embedding_service.search(query=query)
        for result in results:
            print(f"- {result['text']} (similarity: {result['similarity']:.3f})")

if __name__ == "__main__":
    asyncio.run(main())
