import fitz
from docx import Document
from ocr.tesseract import is_tesseract
from ocr.tesseract import extract_text_from_pdf
import os
import chromadb
from dotenv import load_dotenv
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from sentence_transformers import SentenceTransformer
import torch
import gc

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

class LocalEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model):
        self.model = model

    def __call__(self, input: Documents) -> Embeddings:
        return self.model.encode(input).tolist()

class RAGProcessor:
    def __init__(self):
        print("[RAG] Initializing RAGProcessor...")
        self.load_model_and_db()

    def load_model_and_db(self):
        # Get Env
        print("[RAG] Loading environment variables...")
        load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
        
        # Load local embedding model
        base_path = os.path.join(
            PROJECT_ROOT,
            "rag", "models",
            "models--sentence-transformers--all-MiniLM-L6-v2",
            "snapshots"
        )
        snapshot_ids = os.listdir(base_path)
        if not snapshot_ids:
            raise FileNotFoundError(f"No snapshot folders found in {base_path}")
        snapshot_id = snapshot_ids[0]
        model_path = os.path.join(base_path, snapshot_id)
        
        print(f"[RAG] Loading local embedding model (sentence-transformers/all-MiniLM-L6-v2)...{snapshot_id}")
        self.local_embedder = SentenceTransformer(model_path)
        
        embedding_function = LocalEmbeddingFunction(self.local_embedder)

        # Initialize ChromaDB client
        print("[RAG] Initializing ChromaDB persistent client and collection...")
        self.chroma_client = chromadb.PersistentClient(path="./chroma_store")
        self.collection = self.chroma_client.get_or_create_collection(
            "rag_files",
            embedding_function=embedding_function
        )
        print("[RAG] RAGProcessor initialized successfully.")

_rag_processor_instance = None

def wake_rag_processor():
    """Ensure the RAGProcessor is loaded."""
    get_rag_processor()
    
def get_rag_processor():
    global _rag_processor_instance
    if _rag_processor_instance is None:
        _rag_processor_instance = RAGProcessor()
    return _rag_processor_instance

def is_rag_loaded():
    """Return True if the RAGProcessor is currently loaded."""
    return _rag_processor_instance is not None

def unload_rag_processor():
    """Unload the RAGProcessor and free associated resources."""
    global _rag_processor_instance
    if _rag_processor_instance is not None:
        try:
            _rag_processor_instance.chroma_client = None
            _rag_processor_instance.collection = None
            _rag_processor_instance.local_embedder = None
        except Exception:
            pass
        _rag_processor_instance = None
        # If you're using PyTorch model under the hood
        if 'model' in globals():
            del model

        # Delete anything else holding references
        for name in dir():
            if name.startswith("model") or "transformer" in name:
                del globals()[name]

        # Force garbage collection
        gc.collect()

        # If using GPU (optional)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        print(f"[RAG] RAGProcessor unloaded to free memory")

def extract_text(filepath):
    if filepath.lower().endswith(".pdf"):
        doc = fitz.open(filepath)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        if not text or len(text) < 10:
            if is_tesseract():
                print(f"No text discovered, trying as a image...")
                return extract_text_from_pdf(filepath)
            else:
                print(f"No text discovered in PDF and Tesseract is not available. Returning empty string.")
                return ""
        return text
    elif filepath.lower().endswith(".docx"):
        doc = Document(filepath)
        text = "\n".join([p.text for p in doc.paragraphs])
        return text
    else:
        raise ValueError("Unsupported file type. Only PDF and DOCX are supported.")

def add_file_to_chat(filepath, chat_id=None):
    try:
        text = extract_text(filepath)
        if text:
            chunk_size = 1000
            chunk_texts = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
            chunk_ids = [f"{chat_id}_{os.path.basename(filepath)}_chunk_{i}" for i in range(len(chunk_texts))]
            metadatas = [{"chat_id": chat_id, "source": filepath, "chunk": i} for i in range(len(chunk_texts))]

            get_rag_processor().collection.add(
                documents=chunk_texts,
                ids=chunk_ids,
                metadatas=metadatas
            )
            print(f"File '{filepath}' added to ChromaDB in {len(chunk_texts)} chunks.")
            return chunk_ids
        else:
            print(f"No text extracted from file '{filepath}'. Skipping addition to ChromaDB.")
        return []

    except Exception as e:
        print(f"Error adding file '{filepath}' to ChromaDB: {e}")
        return []

def add_text_to_chat(text, source, chat_id=None):
    """Embed arbitrary text into ChromaDB with an associated source string."""
    try:
        if text:
            chunk_size = 1000
            chunk_texts = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
            chunk_ids = [f"{chat_id}_{source}_chunk_{i}" for i in range(len(chunk_texts))]
            metadatas = [{"chat_id": chat_id, "source": source, "chunk": i} for i in range(len(chunk_texts))]

            get_rag_processor().collection.add(
                documents=chunk_texts,
                ids=chunk_ids,
                metadatas=metadatas
            )
            print(f"Text from '{source}' added to ChromaDB in {len(chunk_texts)} chunks.")
            return chunk_ids
        else:
            print(f"No text provided for source '{source}'. Skipping addition to ChromaDB.")
            return []

    except Exception as e:
        print(f"Error adding text for source '{source}' to ChromaDB: {e}")
        return []

def delete_file_from_chromadb(filepath):
    doc_id = os.path.basename(filepath)
    get_rag_processor().collection.delete(ids=[doc_id])
    print(f"File '{filepath}' (ID: {doc_id}) deleted from ChromaDB.")

def delete_file_from_chat(filepath, chat_id=None):
    rag_processor = get_rag_processor()
    results = rag_processor.collection.get(where={"chat_id": chat_id})
    ids = [id_ for id_, meta in zip(results["ids"], results["metadatas"]) if meta.get("source") == filepath]
    if ids:
        rag_processor.collection.delete(ids=ids)
        print(f"Deleted {len(ids)} chunks for file '{filepath}' in chat '{chat_id}' from ChromaDB.")
        return len(ids)
    print(f"No chunks found for file '{filepath}' in chat '{chat_id}'.")
    return 0

def delete_source_from_chat(source, chat_id=None):
    """Delete all chunks associated with a specific source string."""
    rag_processor = get_rag_processor()
    results = rag_processor.collection.get(where={"chat_id": chat_id})
    ids = [id_ for id_, meta in zip(results["ids"], results["metadatas"]) if meta.get("source") == source]
    if ids:
        rag_processor.collection.delete(ids=ids)
        print(f"Deleted {len(ids)} chunks for source '{source}' in chat '{chat_id}' from ChromaDB.")
        return len(ids)
    print(f"No chunks found for source '{source}' in chat '{chat_id}'.")
    return 0

def delete_all_files_from_chat(chat_id=None):
    if not chat_id:
        print("No chat_id provided.")
        return 0

    files = get_files_for_chat(chat_id)
    if not files:
        print(f"No files found for chat_id '{chat_id}'.")
        return 0

    total_deleted_chunks = 0
    for file_path in files:
        deleted_chunks = delete_file_from_chat(file_path, chat_id)
        total_deleted_chunks += deleted_chunks

    print(f"Total deleted chunks for chat_id '{chat_id}': {total_deleted_chunks}")
    return total_deleted_chunks

def query_by_chat_id(chat_id: str, query: str, n_results: int = 5):
    results = get_rag_processor().collection.query(
        query_texts=[query],
        n_results=n_results,
        where={"chat_id": chat_id}
    )

    docs = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]

    return [{"text": doc, "metadata": meta} for doc, meta in zip(docs, metadatas)]

def get_files_for_chat(chat_id: str):
    if not chat_id:
        return []
    results = get_rag_processor().collection.get(where={"chat_id": chat_id})

    if not results or not results.get("metadatas"):
        return []

    unique_files = {meta['source'] for meta in results["metadatas"] if 'source' in meta}

    return list(unique_files)

def main():
    filename = os.path.join(PROJECT_ROOT, "rag", "richesrestaurant.pdf")
    if os.path.exists(filename):
        print(f"Processing {filename}...")
        add_file_to_chat(filename, 'chat123')
        matches = query_by_chat_id(chat_id="chat123", query="How much for a burrito?", n_results=3)

        for match in matches:
            print("Text:", match["text"])
            print("From file:", match["metadata"].get("source"))
            print("---")

        delete_file_from_chat(filename, 'chat123')
    else:
        print(f"File '{filename}' not found in current directory.")

    # try a image based PDF/ocr.
    filename = os.path.join(PROJECT_ROOT, "rag/ocr", "ParksidePaws.pdf")
    if os.path.exists(filename):
        print(f"Processing {filename}...")
        add_file_to_chat(filename, 'chat123')
        matches = query_by_chat_id(chat_id="chat123", query="How much for walk?", n_results=3)

        for match in matches:
            print("Text:", match["text"])
            print("From file:", match["metadata"].get("source"))
            print("---")

        delete_file_from_chat(filename, 'chat123')
    else:
        print(f"File '{filename}' not found in current directory.")

    
if __name__ == "__main__":
    main()

__all__ = [
    "query_by_chat_id",
    "add_file_to_chat",
    "add_text_to_chat",
    "delete_file_from_chat",
    "delete_source_from_chat",
    "get_files_for_chat",
    "delete_all_files_from_chat",
    "unload_rag_processor",
    "is_rag_loaded",
    "wake_rag_processor",
]
