import os
import chromadb
from chromadb.config import Settings

class RAGManager:
    """Manage a ChromaDB instance used for RAG."""

    def __init__(self):
        self.client = None
        self.collection = None

    def load(self, persist_directory: str):
        """Load (or reload) the ChromaDB database from ``persist_directory``."""
        self.close()

        # Ensure the path is absolute and short enough for ChromaDB's internal
        # Unix socket creation. Long paths can exceed the typical 108 character
        # limit, resulting in ``File name too long`` errors on startup.
        persist_directory = os.path.abspath(persist_directory)
        if len(persist_directory) > 90:
            persist_directory = "/tmp/chroma_store"

        self.client = chromadb.PersistentClient(
            Settings(chroma_db_impl="duckdb+parquet", persist_directory=persist_directory)
        )
        self.collection = self.client.get_or_create_collection("rag")
        return self.collection

    def close(self):
        """Persist and shut down the ChromaDB client if it is running."""
        if self.client is None:
            return
        try:
            # Persist any changes to disk
            if hasattr(self.client, "persist"):
                self.client.persist()
            # Newer Chroma versions expose ``reset`` for clean shutdown
            if hasattr(self.client, "reset"):
                self.client.reset()
        finally:
            self.client = None
            self.collection = None
            import gc
            gc.collect()

