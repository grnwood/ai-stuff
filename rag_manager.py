import os
import gc
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings


class LocalEmbeddingFunction(EmbeddingFunction):
    """Wrap a SentenceTransformer model for use with ChromaDB."""

    def __init__(self, model: SentenceTransformer):
        self.model = model

    def __call__(self, input: Documents) -> Embeddings:
        return self.model.encode(input).tolist()

class RAGManager:
    """Manage the SentenceTransformer model and ChromaDB instance used for RAG."""

    def __init__(self):
        self.client = None
        self.collection = None
        self.embedder = None

    def load(self, persist_directory: str, model_path: str | None = None):
        """Load (or reload) the embedding model and ChromaDB database."""
        self.close()

        load_dotenv(os.path.join(os.path.dirname(__file__), '.env'), override=True)

        if model_path is None:
            base = os.path.join(
                os.path.dirname(__file__),
                'ask-server',
                'rag',
                'models',
                'models--sentence-transformers--all-MiniLM-L6-v2',
                'snapshots',
            )
            if os.path.isdir(base):
                snapshots = os.listdir(base)
                if snapshots:
                    model_path = os.path.join(base, snapshots[0])
        if model_path is None:
            model_path = 'sentence-transformers/all-MiniLM-L6-v2'

        self.embedder = SentenceTransformer(model_path)
        embedding_function = LocalEmbeddingFunction(self.embedder)

        self.client = chromadb.PersistentClient(
            Settings(chroma_db_impl='duckdb+parquet', persist_directory=persist_directory)
        )
        self.collection = self.client.get_or_create_collection(
            'rag_files', embedding_function=embedding_function
        )
        return self.collection

    def close(self):
        """Persist and shut down the embedding model and Chroma client."""
        if self.client is None and self.embedder is None:
            return
        try:
            if self.client is not None:
                if hasattr(self.client, "persist"):
                    self.client.persist()
                if hasattr(self.client, "reset"):
                    self.client.reset()
        finally:
            self.client = None
            self.collection = None
            self.embedder = None
            gc.collect()
