import fitz
from docx import Document
import requests
import os
import chromadb
from dotenv import load_dotenv
from chromadb.utils import embedding_functions
from sentence_transformers import SentenceTransformer

# Get Env
print("[RAG] Loading environment variables...")
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
collection = False
local_embedder = None

def load_local_embedder():
    global collection, local_embedder
    if not collection:
        # Load local embedding model
        # Cross-platform relative path
        base_path = os.path.join("rag/models", "models--sentence-transformers--all-MiniLM-L6-v2", "snapshots")

        # Get the first snapshot ID (assuming only one exists)
        snapshot_ids = os.listdir(base_path)
        if not snapshot_ids:
            raise FileNotFoundError(f"No snapshot folders found in {base_path}")
        snapshot_id = snapshot_ids[0]

        # Full path to the model directory
        model_path = os.path.join(base_path, snapshot_id)
        print(f"[RAG] Loading local embedding model (sentence-transformers/all-MiniLM-L6-v2)...{snapshot_id}")
        local_embedder = SentenceTransformer(model_path)
        sentence_transformer_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )

        # Initialize ChromaDB client
        print("[RAG] Initializing ChromaDB persistent client and collection...")
        chroma_client = chromadb.PersistentClient(path="./chroma_store")
        collection = chroma_client.get_or_create_collection("rag_files",
                                        embedding_function=sentence_transformer_fn)


def extract_text(filepath):
    if filepath.lower().endswith(".pdf"):
        doc = fitz.open(filepath)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text
    elif filepath.lower().endswith(".docx"):
        doc = Document(filepath)
        text = "\n".join([p.text for p in doc.paragraphs])
        return text
    else:
        raise ValueError("Unsupported file type. Only PDF and DOCX are supported.")

def embed_text(text):
    global local_embedder
    # Accepts a string or list of strings
    if isinstance(text, str):
        return local_embedder.encode([text])[0].tolist()
    else:
        return local_embedder.encode(text).tolist()

def add_file_to_chat(filepath, chat_id=None):
    try:
        global collection
        load_local_embedder()
        text = extract_text(filepath)
        if text:
            # Split text into chunks (for simplicity, use 1000 chars per chunk)
            chunk_size = 1000
            chunk_texts = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
            chunk_ids = [f"{os.path.basename(filepath)}_chunk_{i}" for i in range(len(chunk_texts))]
            embeddings = [embed_text(chunk) for chunk in chunk_texts]
            metadatas = [{"chat_id": chat_id, "source": filepath, "chunk": i} for i in range(len(chunk_texts))]
            collection.add(
                documents=chunk_texts,
                ids=chunk_ids,
                embeddings=embeddings,
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

def delete_file_from_chromadb(filepath):
    global collection
    load_local_embedder()
    doc_id = os.path.basename(filepath)
    collection.delete(ids=[doc_id])
    print(f"File '{filepath}' (ID: {doc_id}) deleted from ChromaDB.")

def delete_file_from_chat(filepath, chat_id=None):
    global collection
    load_local_embedder()
    results = collection.get(where={"chat_id": chat_id})
    ids = [id_ for id_, meta in zip(results["ids"], results["metadatas"]) if meta.get("source") == filepath]
    if ids:
        collection.delete(ids=ids)
        print(f"Deleted {len(ids)} chunks for file '{filepath}' in chat '{chat_id}' from ChromaDB.")
        return len(ids)
    print(f"No chunks found for file '{filepath}' in chat '{chat_id}'.")
    return 0

def delete_all_files_from_chat(chat_id=None):
    """
    Deletes all files and their associated chunks from ChromaDB for a given chat_id.
    """
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
    """
    Query ChromaDB for the most relevant chunks associated with a specific chat_id.

    Parameters:
        collection: Chroma collection instance
        chat_id (str): ID of the chat session to scope search
        query (str): User's input or question
        n_results (int): Number of top documents to return

    Returns:
        List of dicts with 'text' and 'metadata'
    """
    global collection
    load_local_embedder()
    results = collection.query(
        query_texts=[query],
        n_results=n_results,
        where={"chat_id": chat_id}
    )

    docs = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]

    return [{"text": doc, "metadata": meta} for doc, meta in zip(docs, metadatas)]

def get_files_for_chat(chat_id: str):
    global collection
    load_local_embedder()
    """
    Retrieves all unique file paths associated with a specific chat_id.
    """
    if not chat_id:
        return []
    results = collection.get(where={"chat_id": chat_id})
    
    if not results or not results.get("metadatas"):
        return []

    # Use a set to store unique file paths
    unique_files = {meta['source'] for meta in results["metadatas"] if 'source' in meta}
    
    return list(unique_files)

def main():
    filename = "rag/lukes-transscripts.pdf"
    if os.path.exists(filename):
        print(f"Processing {filename}...")
        add_file_to_chat(filename, 'chat123')
        matches = query_by_chat_id(chat_id="chat123", query="What is Annual GPA for Spanish?", n_results=3)

        for match in matches:
            print("Text:", match["text"])
            print("From file:", match["metadata"].get("source"))
            print("---")

        delete_file_from_chat(filename, 'chat123')
    else:
        print(f"File '{filename}' not found in current directory.")


if __name__ == "__main__":
    main()

# Export collection so it can be imported from ask-client.py
__all__ = ["query_by_chat_id", "collection", "add_file_to_chat", "delete_file_from_chat", "get_files_for_chat", "delete_all_files_from_chat"]

