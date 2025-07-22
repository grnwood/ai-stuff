import os
import sys
import fitz
import gc
import psutil
import tracemalloc
import requests
import multiprocessing
from docx import Document
from dotenv import load_dotenv
from ocr.tesseract import is_tesseract, extract_text_from_pdf
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

_rag_processor_instance = None
_rag_process = None
_rag_conn = None
_IN_WORKER = False

# --------------------------------------------------
# Memory + Diagnostic Helpers
# --------------------------------------------------
def show_memory_snapshot():
    print("Running garbage collection...")
    gc.collect()
    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics('lineno')

    print("\n[ Top 10 memory allocations ]")
    for stat in top_stats[:10]:
        print(stat)

def log_memory_usage():
    process = psutil.Process(os.getpid())
    rss_mb = process.memory_info().rss / 1024 / 1024
    print(f"[Memory] RSS: {rss_mb:.2f} MB")

# --------------------------------------------------
# RAGProcessor definition (used only in subprocess)
# --------------------------------------------------
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
        from sentence_transformers import SentenceTransformer
        import chromadb

        print("[RAG] Loading environment variables...")
        load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

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

        print(f"[RAG] Loading local embedding model... {snapshot_id}")
        self.local_embedder = SentenceTransformer(model_path)
        embedding_function = LocalEmbeddingFunction(self.local_embedder)

        print("[RAG] Initializing ChromaDB persistent client and collection...")
        self.chroma_client = chromadb.PersistentClient(path="./chroma_store")
        self.collection = self.chroma_client.get_or_create_collection(
            "rag_files",
            embedding_function=embedding_function
        )
        print("[RAG] RAGProcessor initialized successfully.")
        show_memory_snapshot()

# --------------------------------------------------
# Background Process and Messaging
# --------------------------------------------------
def _worker_loop(conn):
    global _IN_WORKER, _rag_processor_instance
    _IN_WORKER = True
    while True:
        try:
            cmd, args, kwargs = conn.recv()
        except EOFError:
            break

        if cmd == "stop":
            unload_rag_processor()
            conn.send(True)
            break
        elif cmd == "load":
            get_rag_processor()
            conn.send(True)
        elif cmd == "add_file_to_chat":
            conn.send(add_file_to_chat(*args, **kwargs))
        elif cmd == "add_text_to_chat":
            conn.send(add_text_to_chat(*args, **kwargs))
        elif cmd == "query_by_chat_id":
            conn.send(query_by_chat_id(*args, **kwargs))
        elif cmd == "delete_file_from_chat":
            conn.send(delete_file_from_chat(*args, **kwargs))
        elif cmd == "delete_source_from_chat":
            conn.send(delete_source_from_chat(*args, **kwargs))
        elif cmd == "delete_all_files_from_chat":
            conn.send(delete_all_files_from_chat(*args, **kwargs))
        elif cmd == "get_files_for_chat":
            conn.send(get_files_for_chat(*args, **kwargs))
        elif cmd == "is_rag_loaded":
            conn.send(is_rag_loaded())
        else:
            conn.send(None)
    conn.close()

def _start_rag_process():
    global _rag_process, _rag_conn
    if _rag_process is None or not _rag_process.is_alive():
        parent_conn, child_conn = multiprocessing.Pipe()
        _rag_process = multiprocessing.Process(target=_worker_loop, args=(child_conn,))
        _rag_process.start()
        _rag_conn = parent_conn

def _send_cmd(cmd, *args, **kwargs):
    _start_rag_process()
    _rag_conn.send((cmd, args, kwargs))
    return _rag_conn.recv()

def stop_rag_processor():
    global _rag_process, _rag_conn
    if _rag_conn:
        try:
            _send_cmd("stop")
        except Exception as e:
            print(f"[RAG] stop command failed: {e}")
        _rag_conn.close()
        _rag_process.join()
        _rag_process = None
        _rag_conn = None
        print("[RAG] Subprocess terminated.")

def get_rag_processor():
    global _rag_processor_instance
    if _rag_processor_instance is None:
        _rag_processor_instance = RAGProcessor()
    return _rag_processor_instance

def is_rag_loaded():
    return _send_cmd("is_rag_loaded") if not _IN_WORKER else _rag_processor_instance is not None

def wake_rag_processor():
    return _send_cmd("load")

def unload_rag_processor():
    global _rag_processor_instance
    print("[RAG] Attempting to unload RAGProcessor...")

    try:
        if _rag_processor_instance is not None:
            if hasattr(_rag_processor_instance, "local_embedder"):
                del _rag_processor_instance.local_embedder
            if hasattr(_rag_processor_instance, "collection"):
                del _rag_processor_instance.collection
            if hasattr(_rag_processor_instance, "chroma_client"):
                del _rag_processor_instance.chroma_client
            _rag_processor_instance = None

    except Exception as e:
        print(f"[RAG] Unexpected error during unload: {e}")

    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except ImportError:
        pass

    log_memory_usage()
    show_memory_snapshot()
    print("[RAG] RAGProcessor fully unloaded.")

# --------------------------------------------------
# Public-facing functions for embedding and querying
# --------------------------------------------------
def extract_text(filepath):
    if filepath.lower().endswith(".pdf"):
        doc = fitz.open(filepath)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        if not text or len(text) < 10:
            return extract_text_from_pdf(filepath) if is_tesseract() else ""
        return text
    elif filepath.lower().endswith(".docx"):
        doc = Document(filepath)
        return "\n".join(p.text for p in doc.paragraphs)
    else:
        raise ValueError("Unsupported file type. Only PDF and DOCX are supported.")

def add_file_to_chat(filepath, chat_id=None):
    if _IN_WORKER:
        text = extract_text(filepath)
        if text:
            chunk_size = 1000
            chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
            ids = [f"{chat_id}_{os.path.basename(filepath)}_chunk_{i}" for i in range(len(chunks))]
            metadatas = [{"chat_id": chat_id, "source": filepath, "chunk": i} for i in range(len(chunks))]
            get_rag_processor().collection.add(documents=chunks, ids=ids, metadatas=metadatas)
            return ids
        return []
    return _send_cmd("add_file_to_chat", filepath, chat_id=chat_id)

def add_text_to_chat(text, source, chat_id=None):
    if _IN_WORKER:
        if text:
            chunk_size = 1000
            chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
            ids = [f"{chat_id}_{source}_chunk_{i}" for i in range(len(chunks))]
            metadatas = [{"chat_id": chat_id, "source": source, "chunk": i} for i in range(len(chunks))]
            get_rag_processor().collection.add(documents=chunks, ids=ids, metadatas=metadatas)
            return ids
        return []
    return _send_cmd("add_text_to_chat", text, source, chat_id=chat_id)

def query_by_chat_id(chat_id, query, n_results=5):
    if _IN_WORKER:
        results = get_rag_processor().collection.query(query_texts=[query], n_results=n_results, where={"chat_id": chat_id})
        return [{"text": d, "metadata": m} for d, m in zip(results.get("documents", [[]])[0], results.get("metadatas", [[]])[0])]
    return _send_cmd("query_by_chat_id", chat_id, query, n_results=n_results)

def delete_file_from_chromadb(filepath):
    doc_id = os.path.basename(filepath)
    get_rag_processor().collection.delete(ids=[doc_id])
    print(f"File '{filepath}' (ID: {doc_id}) deleted from ChromaDB.")

def delete_file_from_chat(filepath, chat_id=None):
    if _IN_WORKER:
        rag_processor = get_rag_processor()
        results = rag_processor.collection.get(where={"chat_id": chat_id})
        ids = [id_ for id_, meta in zip(results["ids"], results["metadatas"]) if meta.get("source") == filepath]
        if ids:
            rag_processor.collection.delete(ids=ids)
            print(f"Deleted {len(ids)} chunks for file '{filepath}' in chat '{chat_id}' from ChromaDB.")
            return len(ids)
        print(f"No chunks found for file '{filepath}' in chat '{chat_id}'.")
        return 0
    else:
        return _send_cmd("delete_file_from_chat", filepath, chat_id=chat_id)

def delete_source_from_chat(source, chat_id=None):
    """Delete all chunks associated with a specific source string."""
    if _IN_WORKER:
        rag_processor = get_rag_processor()
        results = rag_processor.collection.get(where={"chat_id": chat_id})
        ids = [id_ for id_, meta in zip(results["ids"], results["metadatas"]) if meta.get("source") == source]
        if ids:
            rag_processor.collection.delete(ids=ids)
            print(f"Deleted {len(ids)} chunks for source '{source}' in chat '{chat_id}' from ChromaDB.")
            return len(ids)
        print(f"No chunks found for source '{source}' in chat '{chat_id}'.")
        return 0
    else:
        return _send_cmd("delete_source_from_chat", source, chat_id=chat_id)

def delete_all_files_from_chat(chat_id=None):
    if _IN_WORKER:
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
    else:
        return _send_cmd("delete_all_files_from_chat", chat_id=chat_id)

def query_by_chat_id(chat_id: str, query: str, n_results: int = 5):
    if _IN_WORKER:
        results = get_rag_processor().collection.query(
            query_texts=[query],
            n_results=n_results,
            where={"chat_id": chat_id}
        )

        docs = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        return [{"text": doc, "metadata": meta} for doc, meta in zip(docs, metadatas)]
    else:
        return _send_cmd("query_by_chat_id", chat_id, query, n_results=n_results)


def get_files_for_chat(chat_id):
    if _IN_WORKER:
        results = get_rag_processor().collection.get(where={"chat_id": chat_id})
        return list({meta['source'] for meta in results.get("metadatas", []) if 'source' in meta})
    return _send_cmd("get_files_for_chat", chat_id)

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
