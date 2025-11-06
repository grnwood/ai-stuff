import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog, colorchooser
from tkinter.scrolledtext import ScrolledText
import requests
import os
import json
import sqlite3
import argparse
import sys
import re
import queue
import socket
import threading
import uuid
import time
from markdown import markdown
from html.parser import HTMLParser
from tkinter import PhotoImage
from dotenv import load_dotenv
from tkinter import font
from PIL import Image
from rag.rag_manager import RAGManager
from bs4 import BeautifulSoup
import platform
from urllib.parse import urljoin, urlparse
import urllib3

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROXY_VERIFY_CERT = os.getenv("PROXY_VERIFY_CERT", "True").lower() == "true"

# Add rag path to sys.path
sys.path.append(os.path.dirname(__file__) + '/rag')

# Global variable for RAG functions, populated by initialize_rag
rag_functions = {}

def initialize_rag():
    """Initializes RAG functions if enabled in settings."""
    global rag_functions
    # Default to 'true' if setting doesn't exist
    if get_setting("enable_rag", "true") == "True":
        try:
            from rag.rag import (
                get_rag_processor,
                add_file_to_chat,
                add_text_to_chat,
                get_files_for_chat,
                delete_file_from_chat,
                delete_source_from_chat,
                query_by_chat_id,
                unload_rag_processor,
                is_rag_loaded,
                wake_rag_processor
            )
            # Store functions for later use
            rag_functions['add_file_to_chat'] = add_file_to_chat
            rag_functions['add_text_to_chat'] = add_text_to_chat
            rag_functions['get_files_for_chat'] = get_files_for_chat
            rag_functions['delete_file_from_chat'] = delete_file_from_chat
            rag_functions['delete_source_from_chat'] = delete_source_from_chat
            rag_functions['query_by_chat_id'] = query_by_chat_id
            rag_functions['unload_rag_processor'] = unload_rag_processor
            rag_functions['is_rag_loaded'] = is_rag_loaded
            rag_functions['wake_rag_processor'] = wake_rag_processor
            print("RAG initialized successfully.")
        except Exception as e:
            print(f"Failed to initialize RAG: {e}")
            messagebox.showerror("RAG Initialization Error", f"Could not initialize RAG components. Files functionality will be disabled.\n\nError: {e}")
            rag_functions = {}
    else:
        print("RAG is disabled in settings.")

def fetch_url_text(url: str) -> str:
    """Retrieve the text content of a URL using BeautifulSoup."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/114.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    validate_ssl = to_bool(get_setting("validate_url_ssl", "True"), default=True)
    resp = requests.get(url, headers=headers, allow_redirects=True, timeout=10, verify=validate_ssl)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "").lower()
    if not any(token in content_type for token in ("text", "html", "xml", "json")):
        raise ValueError(f"Unsupported content type for URL: {content_type or 'unknown'}")

    encoding_header = resp.headers.get("Content-Encoding", "").lower()
    raw_content = resp.content
    if "br" in encoding_header:
        try:
            import brotli  # type: ignore
        except ImportError:
            try:
                import brotlicffi as brotli  # type: ignore
            except ImportError:
                raise ValueError("Response uses Brotli compression but no Brotli decoder is available.")
        raw_content = brotli.decompress(raw_content)
        text_encoding = resp.encoding or resp.apparent_encoding or "utf-8"
        try:
            html = raw_content.decode(text_encoding, errors="ignore")
        except LookupError:
            html = raw_content.decode("utf-8", errors="ignore")
    else:
        if not resp.encoding:
            resp.encoding = resp.apparent_encoding or "utf-8"
        try:
            html = resp.text
        except UnicodeDecodeError:
            html = raw_content.decode(resp.encoding or "utf-8", errors="ignore")

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")
    filtered = "".join(ch if (ch.isprintable() or ch in "\n\t\r") else " " for ch in text)
    cleaned_lines = [line.strip() for line in filtered.splitlines() if line.strip()]
    return "\n".join(cleaned_lines)

load_dotenv()

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

APP_NAME="SlipStreamAI"
DEFAULT_API_URL = os.getenv("PUBLISHED_API", "http://localhost:3000")
DEFAULT_API_SECRET = os.getenv("API_SECRET_TOKEN", "my-secret-token")
DEFAULT_VERIFY_CERT = os.getenv("PROXY_VERIFY_CERT", "False").lower() == "true"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

def _get_default_tcp_port() -> int:
    candidates = [
        os.getenv("API_TCP_PORT"),
        os.getenv("ASK_TCP_PORT"),
        "8765",
    ]
    for value in candidates:
        if value is None:
            continue
        try:
            port = int(value)
            if 1 <= port <= 65535:
                return port
        except ValueError:
            continue
    return 8765


DEFAULT_API_TCP_PORT = _get_default_tcp_port()

DEFAULT_API_TCP_ENABLED = os.getenv("ENABLE_API_TCP_SERVER", "False").strip().lower() in ("true", "1", "yes", "on")

DEFAULT_API_TCP_HOST = (
    os.getenv("API_TCP_HOST")
    or os.getenv("ASK_TCP_HOST")
    or "127.0.0.1"
)

try:
    DEFAULT_API_SERVER_CACHE_TTL = int(os.getenv("API_SERVER_CACHE_TTL", "3600"))
except ValueError:
    DEFAULT_API_SERVER_CACHE_TTL = 3600
DEFAULT_API_SERVER_CACHE_TTL = max(60, DEFAULT_API_SERVER_CACHE_TTL)

CURRENT_SERVER_CONFIG = None

SERVER_CONFIG_FILE = os.path.join(PROJECT_ROOT, "server_configs.json")


def normalize_base_url(url: str) -> str:
    if not url:
        return ""
    return url.rstrip("/")


def compose_url(base_url: str, path: str) -> str:
    base = normalize_base_url(base_url)
    if not path:
        return base
    return urljoin(f"{base}/", path.lstrip("/"))


def to_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "y", "on")
    return bool(value)


def format_bytes(value: int) -> str:
    size = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def build_default_server_configs():
    servers = [{
        "name": "Proxy Server",
        "base_url": normalize_base_url(DEFAULT_API_URL),
        "auth_mode": "proxy",
        "api_secret": DEFAULT_API_SECRET,
        "api_key": "",
        "models_path": "/mods",
        "chat_path": "/v1/chat/completions",
        "verify_ssl": DEFAULT_VERIFY_CERT,
        "default_model": "gpt-3.5-turbo",
        "auto_summarize": True
    }]

    if OPENAI_API_KEY:
        servers.append({
            "name": "OpenAI",
            "base_url": "https://api.openai.com",
            "auth_mode": "openai",
            "api_secret": "",
            "api_key": OPENAI_API_KEY,
            "models_path": "/v1/models",
            "chat_path": "/v1/chat/completions",
            "verify_ssl": True,
            "default_model": "gpt-3.5-turbo",
            "auto_summarize": True
        })
    return servers


def build_auth_headers(server_config: dict) -> dict:
    headers = {}
    auth_mode = (server_config or {}).get("auth_mode", "proxy")
    if auth_mode == "proxy":
        token = (server_config or {}).get("api_secret")
        if token:
            headers["x-api-secret"] = token
    elif auth_mode == "openai":
        api_key = (server_config or {}).get("api_key")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
    else:
        header_name = (server_config or {}).get("custom_header_name")
        header_value = (server_config or {}).get("custom_header_value")
        if header_name and header_value:
            headers[header_name] = header_value
    return headers


def set_current_server_config(config: dict):
    global CURRENT_SERVER_CONFIG
    CURRENT_SERVER_CONFIG = config


def get_current_server_config() -> dict:
    return CURRENT_SERVER_CONFIG

# Default database path. This may be overridden via --db on the command line
# and can be changed at runtime from the settings window.
DB_PATH = "chat_sessions.db"

# File used to persist a list of recently opened databases
RECENT_DB_FILE = "recent_dbs.json"
RECENT_DBS = []

# File used to persist window geometry per database
WINDOW_GEOMETRY_FILE = "window_geometries.json"
WINDOW_GEOMETRIES = {}

def load_recent_dbs():
    """Load the list of recently used database files."""
    if os.path.exists(RECENT_DB_FILE):
        try:
            with open(RECENT_DB_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
    return []

def save_recent_dbs(paths):
    """Persist the list of recently used database files."""
    try:
        with open(RECENT_DB_FILE, "w") as f:
            json.dump(paths, f)
    except Exception:
        pass

def load_window_geometries():
    """Load saved window geometries keyed by database path."""
    if os.path.exists(WINDOW_GEOMETRY_FILE):
        try:
            with open(WINDOW_GEOMETRY_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}

def save_window_geometries(data):
    """Persist window geometries mapping."""
    try:
        with open(WINDOW_GEOMETRY_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass

def get_available_models(server_config=None):
    server = server_config or get_current_server_config()
    if not server:
        return ["gpt-3.5-turbo"]

    fallback_model = server.get("default_model") or "gpt-3.5-turbo"
    base_url = server.get("base_url", "")
    if not base_url:
        return [fallback_model]

    models_path = server.get("models_path") or ("/mods" if server.get("auth_mode") == "proxy" else "/v1/models")
    url = compose_url(base_url, models_path)
    headers = build_auth_headers(server)
    verify = bool(server.get("verify_ssl", True))

    try:
        print(f"Fetching available models from {url}, verify_ssl={verify}")
        response = requests.get(url, headers=headers, verify=verify, timeout=10)
        response.raise_for_status()
        payload = response.json()

        model_ids = []
        if isinstance(payload, dict):
            if "data" in payload and isinstance(payload["data"], list):
                data_list = payload["data"]
                if data_list and isinstance(data_list[0], dict):
                    model_ids = [item.get("id") for item in data_list if item.get("id")]
                else:
                    model_ids = [str(item) for item in data_list if item]
            elif "models" in payload and isinstance(payload["models"], list):
                model_ids = [str(item) for item in payload["models"] if item]
        elif isinstance(payload, list):
            if payload and isinstance(payload[0], dict):
                model_ids = [item.get("id") for item in payload if item.get("id")]
            else:
                model_ids = [str(item) for item in payload if item]

        cleaned_models = sorted({m for m in model_ids if m})
        if cleaned_models:
            return cleaned_models
    except Exception as e:
        print(f"Error fetching models from {url}: {e}")

    return [fallback_model]

# --- Database ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS system_prompts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL UNIQUE,
                    prompt TEXT NOT NULL
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    model TEXT DEFAULT 'gpt-3.5-turbo',
                    server_name TEXT,
                    last_model_used TEXT DEFAULT 'gpt-3.5-turbo',
                    system_prompt TEXT,
                    system_prompt_id INTEGER,
                    parent_id INTEGER,
                    type TEXT DEFAULT 'chat',
                    FOREIGN KEY(parent_id) REFERENCES sessions(id)
                )''')
    c.execute("PRAGMA table_info(sessions)")
    cols = [row[1] for row in c.fetchall()]
    if 'system_prompt_id' not in cols:
        c.execute('ALTER TABLE sessions ADD COLUMN system_prompt_id INTEGER')
        cols.append('system_prompt_id')
    if 'last_model_used' not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN last_model_used TEXT DEFAULT 'gpt-3.5-turbo'")
    c.execute("UPDATE sessions SET last_model_used = model WHERE last_model_used IS NULL OR last_model_used = ''")
    if 'server_name' not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN server_name TEXT")
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
                    session_id INTEGER,
                    role TEXT,
                    content TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS input_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    content TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )''')
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('enable_rag', 'true')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('auto_summarize_chats', 'True')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('validate_url_ssl', 'True')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('enable_api_tcp_server', ?)", ('True' if DEFAULT_API_TCP_ENABLED else 'False',))
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('api_tcp_port', ?)", (str(DEFAULT_API_TCP_PORT),))
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('api_tcp_default_server', '')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('api_tcp_default_model', '')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('api_tcp_create_ui_chats', 'False')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('api_tcp_ephemeral_ttl_minutes', '60')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('api_tcp_folder_name', 'API Chats')")
    c.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('api_tcp_host', ?)",
        (DEFAULT_API_TCP_HOST,),
    )
    conn.commit()
    conn.close()

def save_system_prompt(title, prompt):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO system_prompts (title, prompt) VALUES (?, ?)", (title, prompt))
    conn.commit()
    conn.close()

def get_system_prompts():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, title, prompt FROM system_prompts ORDER BY title")
    prompts = c.fetchall()
    conn.close()
    return prompts

def delete_system_prompt(prompt_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM system_prompts WHERE id = ?", (prompt_id,))
    conn.commit()
    conn.close()

def get_setting(key, default=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else default

def save_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()


class APIChatTCPServer(threading.Thread):
    """Simple TCP server that accepts chat commands from external tools."""

    def __init__(self, app, host="127.0.0.1", port=8765):
        super().__init__(daemon=True)
        self.app = app
        self.host = host
        self.port = port
        self._stop_event = threading.Event()
        self._server_socket = None

    def run(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
                server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server_sock.bind((self.host, self.port))
                server_sock.listen(5)
                server_sock.settimeout(1.0)
                self._server_socket = server_sock
                print(f"API TCP server listening on {self.host}:{self.port}")
                while not self._stop_event.is_set():
                    try:
                        client_socket, addr = server_sock.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                    threading.Thread(
                        target=self.handle_client,
                        args=(client_socket, addr),
                        daemon=True,
                    ).start()
        except Exception as exc:
            print(f"API TCP server error: {exc}")
            try:
                self.app.after(0, lambda e=exc: self.app.on_api_tcp_server_error(e))
            except Exception:
                pass
        finally:
            self._server_socket = None

    def stop(self):
        self._stop_event.set()
        try:
            with socket.create_connection((self.host, self.port), timeout=0.2):
                pass
        except Exception:
            pass
        if self._server_socket:
            try:
                self._server_socket.close()
            except OSError:
                pass
            self._server_socket = None

    def handle_client(self, client_socket, addr):
        addr_repr = f"{addr[0]}:{addr[1]}"
        print(f"API TCP client connected: {addr_repr}")
        try:
            with client_socket:
                reader = client_socket.makefile("r", encoding="utf-8", newline="\n")
                writer = client_socket.makefile("w", encoding="utf-8", newline="\n")
                try:
                    first_raw_line = reader.readline()
                except UnicodeDecodeError:
                    print("API TCP client sent binary or TLS data; closing connection.")
                    return

                if not first_raw_line:
                    return

                first_line = first_raw_line.strip()
                if first_line.upper().startswith(("GET ", "POST ", "OPTIONS ", "HEAD ")):
                    self._handle_http_exchange(client_socket, reader, first_line, addr_repr)
                    return

                self._send_json(writer, {"ok": True, "message": "connected"})

                def iter_lines(initial):
                    if initial:
                        yield initial
                    for subsequent in reader:
                        yield subsequent.strip()

                for raw_line in iter_lines(first_line):
                    if self._stop_event.is_set():
                        break
                    data = (raw_line or "").strip()
                    if not data:
                        continue
                    if data.startswith("/"):
                        response = self.app.handle_api_tcp_command(data)
                        self._send_json(writer, response)
                        continue
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        self._send_json(writer, {"ok": False, "error": "Invalid JSON payload."})
                        continue
                    response = self.app.process_api_tcp_payload(payload)
                    self._send_json(writer, response)
        except Exception as exc:
            print(f"API TCP client error: {exc}")

    def _handle_http_exchange(self, client_socket, reader, first_line, addr_repr):
        try:
            parts = first_line.split()
            if len(parts) < 2:
                self._send_http_response(client_socket, 400, {"error": "Malformed request line."})
                return
            method = parts[0].upper()
            path = parts[1]

            headers = {}
            while True:
                try:
                    header_line = reader.readline()
                except UnicodeDecodeError:
                    self._send_http_response(client_socket, 400, {"error": "Invalid header encoding."})
                    return
                if header_line in ("", "\n", "\r\n"):
                    break
                if ":" not in header_line:
                    continue
                key, value = header_line.split(":", 1)
                headers[key.strip().lower()] = value.strip()

            if method == "OPTIONS":
                self._send_http_response(client_socket, 204, None, extra_headers={
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type",
                })
                return

            if method == "GET" and path == "/models":
                payload = self.app.describe_api_tcp_servers()
                self._send_http_response(client_socket, 200, payload)
                return

            if method == "POST" and path in ("/chat", "/chats"):
                content_length = headers.get("content-length")
                if not content_length:
                    self._send_http_response(client_socket, 411, {"error": "Missing Content-Length header."})
                    return
                try:
                    length = int(content_length)
                except ValueError:
                    self._send_http_response(client_socket, 400, {"error": "Invalid Content-Length."})
                    return

                body = reader.read(length)
                if body is None:
                    body = ""
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError as exc:
                    self._send_http_response(client_socket, 400, {"error": f"Invalid JSON payload: {exc}"})
                    return

                response = self.app.process_api_tcp_payload(payload)
                self._send_http_response(client_socket, 200, response)
                return

            self._send_http_response(client_socket, 404, {"error": "Endpoint not found."})
        except Exception as exc:
            print(f"API TCP HTTP error from {addr_repr}: {exc}")
            try:
                self._send_http_response(client_socket, 500, {"error": "Internal server error."})
            except Exception:
                pass

    def _send_http_response(self, client_socket, status_code, payload, extra_headers=None):
        reason_map = {
            200: "OK",
            204: "No Content",
            400: "Bad Request",
            404: "Not Found",
            411: "Length Required",
            500: "Internal Server Error",
        }
        reason = reason_map.get(status_code, "OK")
        body = ""
        if payload is None:
            body_bytes = b""
        elif isinstance(payload, str):
            body = payload
            body_bytes = body.encode("utf-8")
        else:
            body = json.dumps(payload, indent=2)
            body_bytes = body.encode("utf-8")

        headers = {
            "Content-Type": "application/json" if payload is not None else "text/plain",
            "Content-Length": str(len(body_bytes)),
            "Access-Control-Allow-Origin": "*",
            "Connection": "close",
        }
        if extra_headers:
            headers.update(extra_headers)

        header_lines = [f"HTTP/1.1 {status_code} {reason}"]
        for key, value in headers.items():
            header_lines.append(f"{key}: {value}")
        response = "\r\n".join(header_lines) + "\r\n\r\n"
        try:
            client_socket.sendall(response.encode("utf-8") + body_bytes)
        finally:
            client_socket.close()

    def _send_json(self, writer, payload):
        try:
            writer.write(json.dumps(payload) + "\n")
            writer.flush()
        except Exception as exc:
            print(f"API TCP send error: {exc}")


class ServerManager:
    SERVERS_KEY = "api_servers"
    ACTIVE_SERVER_KEY = "active_server"
    CONFIG_FILE = SERVER_CONFIG_FILE

    def __init__(self):
        self._servers_cache = None
        self._data = self._load_file()

    def _load_file(self):
        data = {}
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        data = loaded
            except Exception as exc:
                print(f"Failed to load server configuration file: {exc}")

        if not data:
            legacy_raw = get_setting(self.SERVERS_KEY)
            legacy_servers = []
            if legacy_raw:
                try:
                    parsed = json.loads(legacy_raw)
                    if isinstance(parsed, list):
                        legacy_servers = parsed
                    elif isinstance(parsed, dict):
                        legacy_servers = list(parsed.values())
                except Exception as exc:
                    print(f"Failed to parse legacy server configuration: {exc}")
            if legacy_servers:
                data["servers"] = legacy_servers
                legacy_active = get_setting(self.ACTIVE_SERVER_KEY)
                if legacy_active:
                    data["active_server"] = legacy_active

        if "servers" not in data or not data.get("servers"):
            data["servers"] = build_default_server_configs()

        if not data.get("active_server") and data["servers"]:
            data["active_server"] = data["servers"][0]["name"]

        self._data = data
        self._save_file()
        return data

    def _save_file(self):
        try:
            with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except Exception as exc:
            print(f"Failed to save server configuration file: {exc}")

    def load_servers(self):
        if self._servers_cache is not None:
            return list(self._servers_cache)

        servers = self._data.get("servers", [])
        if not servers:
            servers = build_default_server_configs()

        normalized = [self._normalize_server(entry) for entry in servers if entry]
        self._servers_cache = normalized
        self._data["servers"] = normalized
        if normalized and not self._data.get("active_server"):
            self._data["active_server"] = normalized[0]["name"]
        self._save_file()
        return list(normalized)

    def save_servers(self, servers):
        normalized = [self._normalize_server(entry) for entry in servers if entry]
        self._servers_cache = normalized
        self._data["servers"] = normalized
        if normalized and self._data.get("active_server") not in [srv["name"] for srv in normalized]:
            self._data["active_server"] = normalized[0]["name"]
        if not normalized:
            self._data["active_server"] = None
        self._save_file()
        return list(normalized)

    def list_server_names(self):
        return [server["name"] for server in self.load_servers()]

    def get_server(self, name):
        for server in self.load_servers():
            if server["name"] == name:
                return server
        return None

    def add_or_update_server(self, server):
        servers = self.load_servers()
        target_name = server.get("name")
        original_name = server.get("original_name")
        updated = False
        for idx, existing in enumerate(servers):
            if existing["name"] == target_name or (original_name and existing["name"] == original_name):
                servers[idx] = self._normalize_server(server)
                updated = True
                break
        if not updated:
            if any(existing["name"] == target_name for existing in servers):
                raise ValueError(f"A server named '{target_name}' already exists.")
            servers.append(self._normalize_server(server))
        elif original_name and self._data.get("active_server") == original_name:
            self._data["active_server"] = target_name
        self.save_servers(servers)
        return self.get_server(target_name)

    def delete_server(self, name):
        servers = [server for server in self.load_servers() if server["name"] != name]
        if not servers:
            servers = build_default_server_configs()
        self.save_servers(servers)
        active_name = self.get_active_server_name()
        if active_name == name and servers:
            self.set_active_server(servers[0]["name"])
        return self.load_servers()

    def get_active_server_name(self):
        active_name = self._data.get("active_server")
        available_names = self.list_server_names()
        if active_name in available_names:
            return active_name
        if available_names:
            active_name = available_names[0]
            self.set_active_server(active_name)
            return active_name
        return None

    def get_active_server(self):
        active_name = self.get_active_server_name()
        return self.get_server(active_name)

    def set_active_server(self, name):
        if name and self.get_server(name):
            self._data["active_server"] = name
            self._save_file()
            self._servers_cache = None
            self.load_servers()

    def _normalize_server(self, entry):
        entry = entry or {}
        auth_mode = entry.get("auth_mode") or ("proxy" if entry.get("api_secret") else "openai")
        base_url = normalize_base_url(entry.get("base_url", ""))
        models_path = entry.get("models_path") or ("/mods" if auth_mode == "proxy" else "/v1/models")
        chat_path = entry.get("chat_path") or "/v1/chat/completions"
        name = entry.get("name") or (base_url or "Server")
        auto_summarize = to_bool(entry.get("auto_summarize"), default=True)
        default_model = entry.get("default_model") or "gpt-3.5-turbo"
        return {
            "name": name,
            "base_url": base_url,
            "auth_mode": auth_mode,
            "api_secret": entry.get("api_secret", ""),
            "api_key": entry.get("api_key", ""),
            "models_path": models_path,
            "chat_path": chat_path,
            "verify_ssl": bool(entry.get("verify_ssl", True)),
            "custom_header_name": entry.get("custom_header_name", ""),
            "custom_header_value": entry.get("custom_header_value", ""),
            "default_model": default_model,
            "auto_summarize": auto_summarize,
            "timeout": entry.get("timeout", "")
        }


class ServerConfigDialog(simpledialog.Dialog):
    def __init__(self, parent, title, server=None):
        self.server = server or {}
        self.original_name = self.server.get("name") if self.server else None
        self.result = None
        super().__init__(parent, title)

    def body(self, master):
        ttk.Label(master, text="Name:").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(value=self.server.get("name", ""))
        self.name_entry = ttk.Entry(master, textvariable=self.name_var, width=40)
        self.name_entry.grid(row=0, column=1, sticky="ew", padx=(5, 0))

        ttk.Label(master, text="Base URL:").grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.base_var = tk.StringVar(value=self.server.get("base_url", ""))
        self.base_entry = ttk.Entry(master, textvariable=self.base_var, width=40)
        self.base_entry.grid(row=1, column=1, sticky="ew", padx=(5, 0), pady=(5, 0))

        ttk.Label(master, text="Auth Mode:").grid(row=2, column=0, sticky="w", pady=(5, 0))
        self.auth_mode_var = tk.StringVar(value=self.server.get("auth_mode", "proxy"))
        self.auth_mode_combo = ttk.Combobox(master, textvariable=self.auth_mode_var, state="readonly")
        self.auth_mode_combo['values'] = ("proxy", "openai", "custom")
        self.auth_mode_combo.grid(row=2, column=1, sticky="ew", padx=(5, 0), pady=(5, 0))
        self.auth_mode_combo.bind('<<ComboboxSelected>>', lambda e: self._on_auth_mode_change())

        ttk.Label(master, text="API Secret (proxy):").grid(row=3, column=0, sticky="w", pady=(5, 0))
        self.api_secret_var = tk.StringVar(value=self.server.get("api_secret", ""))
        self.api_secret_entry = ttk.Entry(master, textvariable=self.api_secret_var, width=40)
        self.api_secret_entry.grid(row=3, column=1, sticky="ew", padx=(5, 0), pady=(5, 0))

        ttk.Label(master, text="API Key (OpenAI):").grid(row=4, column=0, sticky="w", pady=(5, 0))
        self.api_key_var = tk.StringVar(value=self.server.get("api_key", ""))
        self.api_key_entry = ttk.Entry(master, textvariable=self.api_key_var, width=40)
        self.api_key_entry.grid(row=4, column=1, sticky="ew", padx=(5, 0), pady=(5, 0))

        ttk.Label(master, text="Custom Header Name:").grid(row=5, column=0, sticky="w", pady=(5, 0))
        self.custom_header_name_var = tk.StringVar(value=self.server.get("custom_header_name", ""))
        self.custom_header_name_entry = ttk.Entry(master, textvariable=self.custom_header_name_var, width=40)
        self.custom_header_name_entry.grid(row=5, column=1, sticky="ew", padx=(5, 0), pady=(5, 0))

        ttk.Label(master, text="Custom Header Value:").grid(row=6, column=0, sticky="w", pady=(5, 0))
        self.custom_header_value_var = tk.StringVar(value=self.server.get("custom_header_value", ""))
        self.custom_header_value_entry = ttk.Entry(master, textvariable=self.custom_header_value_var, width=40)
        self.custom_header_value_entry.grid(row=6, column=1, sticky="ew", padx=(5, 0), pady=(5, 0))

        ttk.Label(master, text="Models Path:").grid(row=7, column=0, sticky="w", pady=(5, 0))
        self.models_path_var = tk.StringVar(value=self.server.get("models_path", ""))
        self.models_path_entry = ttk.Entry(master, textvariable=self.models_path_var, width=40)
        self.models_path_entry.grid(row=7, column=1, sticky="ew", padx=(5, 0), pady=(5, 0))

        ttk.Label(master, text="Chat Path:").grid(row=8, column=0, sticky="w", pady=(5, 0))
        self.chat_path_var = tk.StringVar(value=self.server.get("chat_path", ""))
        self.chat_path_entry = ttk.Entry(master, textvariable=self.chat_path_var, width=40)
        self.chat_path_entry.grid(row=8, column=1, sticky="ew", padx=(5, 0), pady=(5, 0))

        ttk.Label(master, text="Timeout (seconds, optional):").grid(row=9, column=0, sticky="w", pady=(5, 0))
        timeout_value = self.server.get("timeout")
        self.timeout_var = tk.StringVar(value=str(timeout_value) if timeout_value not in [None, ""] else "")
        self.timeout_entry = ttk.Entry(master, textvariable=self.timeout_var, width=40)
        self.timeout_entry.grid(row=9, column=1, sticky="ew", padx=(5, 0), pady=(5, 0))

        available_models = get_available_models(self.server)
        default_model = self.server.get("default_model")
        if not default_model:
            default_model = available_models[0] if available_models else "gpt-3.5-turbo"
        self.default_model_var = tk.StringVar(value=default_model)
        ttk.Label(master, text="Default Model:").grid(row=10, column=0, sticky="w", pady=(5, 0))
        self.default_model_dropdown = ttk.Combobox(master, textvariable=self.default_model_var, state="readonly")
        self.default_model_dropdown['values'] = available_models if available_models else [default_model]
        self.default_model_dropdown.grid(row=10, column=1, sticky="ew", padx=(5, 0), pady=(5, 0))

        self.auto_summarize_var = tk.BooleanVar(value=to_bool(self.server.get("auto_summarize"), default=True))
        self.auto_summarize_check = ttk.Checkbutton(master, text="Auto summarize chats?", variable=self.auto_summarize_var)
        self.auto_summarize_check.grid(row=11, column=0, columnspan=2, sticky="w", padx=(5, 0), pady=(5, 0))

        self.verify_var = tk.BooleanVar(value=bool(self.server.get("verify_ssl", True)))
        self.verify_check = ttk.Checkbutton(master, text="Verify SSL certificates", variable=self.verify_var)
        self.verify_check.grid(row=12, column=1, sticky="w", padx=(5, 0), pady=(5, 0))

        self._on_auth_mode_change()

        master.columnconfigure(1, weight=1)
        return self.name_entry

    def _on_auth_mode_change(self):
        mode = self.auth_mode_var.get()
        proxy_state = "normal" if mode == "proxy" else "disabled"
        openai_state = "normal" if mode == "openai" else "disabled"
        custom_state = "normal" if mode == "custom" else "disabled"

        self.api_secret_entry.configure(state=proxy_state)
        self.api_key_entry.configure(state=openai_state)
        self.custom_header_name_entry.configure(state=custom_state)
        self.custom_header_value_entry.configure(state=custom_state)

        if not self.models_path_var.get().strip():
            default_models_path = "/mods" if mode == "proxy" else "/v1/models"
            self.models_path_var.set(default_models_path)
        if not self.chat_path_var.get().strip():
            self.chat_path_var.set("/v1/chat/completions")

    def validate(self):
        name = self.name_var.get().strip()
        base = self.base_var.get().strip()
        if not name:
            messagebox.showerror("Validation Error", "Name is required.", parent=self)
            return False
        if not base:
            messagebox.showerror("Validation Error", "Base URL is required.", parent=self)
            return False
        return True

    def apply(self):
        auth_mode = self.auth_mode_var.get()
        models_path = self.models_path_var.get().strip() or ("/mods" if auth_mode == "proxy" else "/v1/models")
        chat_path = self.chat_path_var.get().strip() or "/v1/chat/completions"
        timeout_raw = self.timeout_var.get().strip()
        timeout_value = ""
        if timeout_raw:
            try:
                timeout_value = float(timeout_raw)
            except ValueError:
                timeout_value = timeout_raw

        selected_default_model = self.default_model_var.get()
        if not selected_default_model:
            available_models = get_available_models({
                "base_url": self.base_var.get().strip(),
                "models_path": self.models_path_var.get().strip(),
                "auth_mode": self.auth_mode_var.get(),
                "api_secret": self.api_secret_var.get().strip(),
                "api_key": self.api_key_var.get().strip(),
                "verify_ssl": self.verify_var.get()
            })
            if available_models:
                selected_default_model = available_models[0]
            else:
                selected_default_model = "gpt-3.5-turbo"

        self.result = {
            "name": self.name_var.get().strip(),
            "base_url": self.base_var.get().strip(),
            "auth_mode": auth_mode,
            "api_secret": self.api_secret_var.get().strip(),
            "api_key": self.api_key_var.get().strip(),
            "custom_header_name": self.custom_header_name_var.get().strip(),
            "custom_header_value": self.custom_header_value_var.get().strip(),
            "models_path": models_path,
            "chat_path": chat_path,
            "default_model": selected_default_model,
            "auto_summarize": self.auto_summarize_var.get(),
            "verify_ssl": self.verify_var.get(),
            "timeout": timeout_value,
            "original_name": self.original_name,
        }

def get_sessions():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT id, name, model, server_name, last_model_used, system_prompt, system_prompt_id, parent_id, type
                 FROM sessions ORDER BY id""")
    sessions = c.fetchall()
    conn.close()
    return sessions

def get_session_by_id(session_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT id, name, model, server_name, last_model_used, system_prompt, system_prompt_id, parent_id, type
                 FROM sessions WHERE id = ?""", (session_id,))
    row = c.fetchone()
    conn.close()
    return row

def create_session(name, model='gpt-3.5-turbo', system_prompt='', type='chat', parent_id=None, system_prompt_id=None,
                   last_model_used=None, server_name=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """INSERT INTO sessions (name, model, server_name, last_model_used, system_prompt, system_prompt_id, type, parent_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, model, server_name, last_model_used or model, system_prompt, system_prompt_id, type, parent_id),
    )
    conn.commit()
    session_id = c.lastrowid
    conn.close()
    return session_id


def update_session_model(session_id, model):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE sessions SET model = ? WHERE id = ?", (model, session_id))
    conn.commit()
    conn.close()

def update_session_server(session_id, server_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE sessions SET server_name = ? WHERE id = ?", (server_name, session_id))
    conn.commit()
    conn.close()


def update_session_system_prompt(session_id, system_prompt):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE sessions SET system_prompt = ? WHERE id = ?", (system_prompt, session_id))
    conn.commit()
    conn.close()

def update_session_system_prompt_id(session_id, prompt_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE sessions SET system_prompt_id = ? WHERE id = ?", (prompt_id, session_id))
    conn.commit()
    conn.close()


def update_session_last_model_used(session_id, model):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE sessions SET last_model_used = ? WHERE id = ?", (model, session_id))
    conn.commit()
    conn.close()

def get_messages(session_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role, content FROM messages WHERE session_id = ?", (session_id,))
    messages = c.fetchall()
    conn.close()
    return messages

def save_message(session_id, role, content):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)", (session_id, role, content))
    conn.commit()
    conn.close()

def delete_message_by_content(session_id, content):
    """Delete messages matching the given content for a session."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM messages WHERE session_id = ? AND content = ?", (session_id, content))
    conn.commit()
    conn.close()

def save_input_history(session_id, content):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO input_history (session_id, content) VALUES (?, ?)", (session_id, content))
    conn.commit()
    conn.close()

def get_input_history(session_id, limit=25):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT content FROM input_history WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?", (session_id, limit))
    history = [row[0] for row in c.fetchall()]
    conn.close()
    return list(reversed(history))

def delete_input_history_for_session(session_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM input_history WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()

def update_session_name(session_id, new_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE sessions SET name = ? WHERE id = ?", (new_name, session_id))
    conn.commit()
    conn.close()

def delete_session_and_messages(session_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    c.execute("DELETE FROM input_history WHERE session_id = ?", (session_id,))
    c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()

# --- API ---
def stream_and_process_response(resp, widget):
    assistant_full_reply = ""
    buffer = ""
    for line in resp.iter_lines():
        if line:
            decoded_line = line.decode('utf-8')
            if decoded_line.startswith("data: "):
                json_data = decoded_line[len("data: "):]
                if json_data == "[DONE]":
                    break
                try:
                    data = json.loads(json_data)
                    if 'choices' in data and len(data['choices']) > 0:
                        delta = data['choices'][0]['delta']
                        if 'content' in delta:
                            content_chunk = delta['content']
                            assistant_full_reply += content_chunk
                            buffer += content_chunk
                            if widget:
                                # This is a simplified approach for real-time rendering.
                                # For a more robust solution, you might need to parse the buffer
                                # and apply tags incrementally.
                                widget.configure(state="normal")
                                widget.insert(tk.END, content_chunk)
                                widget.see(tk.END)
                                widget.update_idletasks()
                except json.JSONDecodeError:
                    print(f"Skipping non-JSON line: {decoded_line}")
    
    # Final rendering after the stream is complete
    if widget:
        # This is where you could re-render the whole response for accuracy
        pass

    return assistant_full_reply

def _extract_non_stream_content(data):
    def flatten(content):
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    if "text" in item and item["text"]:
                        parts.append(str(item["text"]))
                    elif "content" in item and item["content"]:
                        parts.append(str(item["content"]))
                elif item is not None:
                    parts.append(str(item))
            return "".join(parts)
        if content is None:
            return ""
        return str(content)

    if not isinstance(data, dict):
        return flatten(data)

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0] or {}
        message_block = choice.get("message")
        if isinstance(message_block, dict):
            content = message_block.get("content")
            if content:
                return flatten(content)
        delta_block = choice.get("delta")
        if isinstance(delta_block, dict):
            content = delta_block.get("content")
            if content:
                return flatten(content)
        elif isinstance(delta_block, list):
            return flatten(delta_block)

    fallback = data.get("message") or data.get("text") or data.get("content")
    return flatten(fallback)


def send_to_api(session_name, messages, model, current_session_id, server_config=None, widget=None, save_message_to_db=True, stream=True):
    server = server_config or get_current_server_config()
    if not server:
        raise ValueError("No server configured. Please configure a server in Settings.")

    base_url = server.get("base_url", "")
    chat_path = server.get("chat_path") or "/v1/chat/completions"
    if not base_url:
        raise ValueError("Selected server does not have a base URL configured.")

    url = compose_url(base_url, chat_path)
    verify = bool(server.get("verify_ssl", True))
    headers = {"Content-Type": "application/json"}
    headers.update(build_auth_headers(server))
    timeout_raw = server.get("timeout", "")
    try:
        timeout = float(timeout_raw) if str(timeout_raw).strip() else 120
    except (ValueError, TypeError):
        timeout = 120

    payload = {
        "model": model,
        "messages": messages,
        "stream": bool(stream)
    }

    assistant_full_reply = ""
    if widget:
        widget.configure(state="normal")
        widget.insert(tk.END, "Assistant:\n", ("assistant_tag")) # Start assistant message
        widget.see(tk.END)
        widget.update_idletasks()

    if stream:
        with requests.post(url, json=payload, headers=headers, stream=True, verify=verify, timeout=timeout) as resp:
            resp.raise_for_status()
            assistant_full_reply = stream_and_process_response(resp, widget)
    else:
        resp = requests.post(url, json=payload, headers=headers, stream=False, verify=verify, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        assistant_full_reply = _extract_non_stream_content(data)
        if widget:
            render_markdown_in_widget(widget, assistant_full_reply)
            widget.insert(tk.END, "\n\n")
            widget.see(tk.END)
            widget.update_idletasks()
        
    # Save the complete assistant reply after streaming is done
    if save_message_to_db:
        save_message(current_session_id, "assistant", assistant_full_reply)
    return assistant_full_reply


class HTMLToTkinter(HTMLParser):
    def __init__(self, text_widget):
        super().__init__()
        self.widget = text_widget
        self.tag_stack = []
        self.list_counter = 0
        self.in_pre = False

        # Table handling
        self.in_table = False
        self.table_data = []
        self.current_row = []
        self.current_cell = ""

    def handle_starttag(self, tag, attrs):
        self.tag_stack.append(tag)

        if tag == 'pre':
            self.in_pre = True
            return

        if tag == 'table':
            self.in_table = True
            self.table_data = []
            return

        if self.in_table:
            if tag == 'tr':
                self.current_row = []
            elif tag in ['td', 'th']:
                self.current_cell = ""
            return

        if tag == 'ol':
            self.list_counter = 1
        elif tag == 'li':
            # Check if we're inside an <ol>
            if 'ol' in self.tag_stack:
                self.widget.insert(tk.END, f"{self.list_counter}. ", ("li",))
                self.list_counter += 1
            else:
                self.widget.insert(tk.END, "• ", ("li",))
        elif tag == 'br':
            self.widget.insert(tk.END, "\n")
        elif tag == 'hr':
            self.widget.insert(tk.END, "\n" + "—"*20 + "\n")

    def handle_endtag(self, tag):
        # ... use self.tag_stack before popping ...
        if tag == 'ol':
            self.list_counter = 0
            self.widget.insert(tk.END, "\n")
    
        if self.tag_stack:
            self.tag_stack.pop()

        if tag == 'pre':
            self.in_pre = False
            self.widget.insert(tk.END, "\n")
            return

        if tag == 'table':
            self.in_table = False
            self.format_and_insert_table()
            return

        if self.in_table:
            if tag == 'tr':
                self.table_data.append(self.current_row)
            elif tag in ['td', 'th']:
                self.current_row.append(self.current_cell.strip())
            return

        if tag == 'ol':
            self.list_counter = 0
            self.widget.insert(tk.END, "\n")  # Only one newline after the whole list

        elif tag == 'ul':
            self.widget.insert(tk.END, "\n")  # Only one newline after the whole list

        # Add this for li:
        elif tag == 'li':
            self.widget.insert(tk.END, "\n")

        if tag in ["h1", "h2", "h3", "pre"]:
            self.widget.insert(tk.END, "\n")


    def handle_data(self, data):
         # Ignore whitespace-only data inside lists
        if self.tag_stack and self.tag_stack[-1] in ("li", "ol", "ul") and data.strip() == "":
            return
        if self.in_pre:
            self.widget.insert(tk.END, data, ("pre",))
            return
        if self.in_table:
            self.current_cell += data
            return
        if self.in_pre:
            self.widget.insert(tk.END, data, ("pre",))
            return
            
        if self.in_table:
            self.current_cell += data
            return

        # Non-table content
        tags = tuple(self.tag_stack)
        tkinter_tags = []
        for t in tags:
            if t in ["h1", "h2", "h3", "p", "li", "pre", "code"]:
                tkinter_tags.append(t)
            elif t in ["b", "strong"]:
                tkinter_tags.append("bold")
            elif t in ["i", "em"]:
                tkinter_tags.append("italic")

        self.widget.insert(tk.END, data, tuple(tkinter_tags))

    def format_and_insert_table(self):
        if not self.table_data:
            return

        num_columns = max(len(row) for row in self.table_data) if self.table_data else 0
        if num_columns == 0:
            return

        col_widths = [0] * num_columns
        for row in self.table_data:
            for i, cell in enumerate(row):
                if i < num_columns:
                    if len(cell) > col_widths[i]:
                        col_widths[i] = len(cell)

        builder = []
        is_header = True
        for row in self.table_data:
            padded_row = row + [''] * (num_columns - len(row))
            line = "| " + " | ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(padded_row)) + " |"
            builder.append(line)
            if is_header and len(self.table_data) > 1:
                separator = "|-" + "-|- ".join("-" * col_widths[i] for i in range(num_columns)) + "-|"
                builder.append(separator)
                is_header = False
        
        formatted_table = "\n".join(builder) + "\n"
        self.widget.insert(tk.END, formatted_table, ("table",))

def render_markdown_in_widget(widget, md):
    # Using 'fenced_code' for better code block handling
    html = markdown(md, extensions=['tables', 'fenced_code'])
    parser = HTMLToTkinter(widget)
    parser.feed(html)



class ToolTip:
    def __init__(self, widget):
        self.widget = widget
        self.tip_window = None
        self.id = None
        self.x = self.y = 0

    def showtip(self, text):
        """Display text in tooltip window"""
        self.text = text
        if self.tip_window or not self.text:
            return
        x, y = self.widget.winfo_pointerxy()
        x = x + 25
        y = y + 20
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(1)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                      background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                      font=("tahoma", "8", "normal"))
        label.pack(ipadx=1)

    def hidetip(self):
        tw = self.tip_window
        self.tip_window = None
        if tw:
            tw.destroy()

def create_tooltip(widget, text_func):
    tool_tip = ToolTip(widget)
    def enter(event):
        text = text_func()
        if text:
            tool_tip.showtip(text)
    def leave(event):
        tool_tip.hidetip()
    widget.bind('<Enter>', enter)
    widget.bind('<Leave>', leave)

class ChatApp(tk.Tk):
    def __init__(self):
        super().__init__()
        
        self.title("SlipstreamAI")
        self.geometry("1000x600")

        # Set icon depending on platform
        base_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(base_dir, "assets", "slipstreamAI.ico")  # use full path
        if sys.platform.startswith("win"):
            self.iconbitmap(default=icon_path)
        else:
            # On Linux/macOS, use PhotoImage (PNG or GIF)
            icon_path = os.path.join(base_dir, "assets", "slipstreamAI.png")  # use full path            icon_image = tk.PhotoImage(file=icon_path)
            self.icon_img = PhotoImage(file=icon_path)
            self.iconphoto(True, self.icon_img)  # ← this sets the window icon
        
        # Track context menus for global dismissal
        self.context_menus = []

        # Manager for optional RAG support using ChromaDB
        self.rag_manager = RAGManager()

        init_db()
        self.server_manager = ServerManager()
        self.server_configs = self.server_manager.load_servers()
        self.current_server_config = self.server_manager.get_active_server()
        if not self.current_server_config and self.server_configs:
            self.current_server_config = self.server_configs[0]
            self.server_manager.set_active_server(self.current_server_config["name"])
        set_current_server_config(self.current_server_config)

        self.session_id = None
        self.session_name = None
        self.message_history = []
        self.history_index = -1
        self.chat_files = []
        self.rag_enabled = get_setting("enable_rag", "True") == "True"
        self.last_model_used = None

        self.api_tcp_enabled = to_bool(get_setting("enable_api_tcp_server", "False"), default=DEFAULT_API_TCP_ENABLED)
        self.api_tcp_port = self._coerce_tcp_port(get_setting("api_tcp_port", str(DEFAULT_API_TCP_PORT)))
        self.api_tcp_host = get_setting("api_tcp_host", DEFAULT_API_TCP_HOST) or DEFAULT_API_TCP_HOST
        default_server_name = self.current_server_config["name"] if self.current_server_config else ""
        default_model_name = self.current_server_config.get("default_model") if self.current_server_config else ""
        self.api_tcp_default_server = get_setting("api_tcp_default_server", "") or default_server_name
        self.api_tcp_default_model = get_setting("api_tcp_default_model", "") or (default_model_name or "")
        self.api_tcp_create_ui_chats = to_bool(get_setting("api_tcp_create_ui_chats", "False"), default=False)
        self.api_tcp_ephemeral_ttl_minutes = self._coerce_positive_int(get_setting("api_tcp_ephemeral_ttl_minutes", "60"), default=60)
        self.api_tcp_folder_name = (get_setting("api_tcp_folder_name", "API Chats") or "API Chats").strip() or "API Chats"
        self.api_tcp_server_thread = None
        self.api_tcp_ephemeral_chats = {}
        self.api_tcp_notifications = queue.Queue()
        self.api_tcp_ephemeral_cleanup_job = None
        self._ephemeral_stats_var = None
        self.api_tcp_folder_id = None
        self.api_server_models_cache = {}
        self.api_server_cache_ttl = DEFAULT_API_SERVER_CACHE_TTL
        self.api_server_cache_lock = threading.Lock()

        initial_server_name = self.current_server_config["name"] if self.current_server_config else ""
        self.server_var = tk.StringVar(value=initial_server_name)

        self.theme = tk.StringVar(value=get_setting("theme", "light"))
        self.chat_font = tk.StringVar(value=get_setting("chat_font", "TkDefaultFont"))
        self.chat_font_size = tk.IntVar(value=get_setting("chat_font_size", 10))
        self.ui_font = tk.StringVar(value=get_setting("ui_font", "TkDefaultFont"))
        self.ui_font_size = tk.IntVar(value=get_setting("ui_font_size", 12))
        self.selection_bg = tk.StringVar(value=get_setting("selection_bg", "#b2d7ff"))
        self.selection_fg = tk.StringVar(value=get_setting("selection_fg", "black"))
        self.current_system_prompt_id = None

        self.chat_icon = tk.PhotoImage(file=os.path.join("ask-server/assets", "comment-alt.png"))
        self.folder_icon = tk.PhotoImage(file=os.path.join("ask-server/assets", "folder-open.png"))
        self.space = tk.PhotoImage(width=5, height=1)

        self.build_gui()
        self.load_system_prompts_to_dropdown()
        self.apply_theme()
        self.apply_font()
        self.apply_ui_font()
        self.apply_selection_colors()
        self.load_sessions()
        self.update_input_widgets_state()

        self.bind_all("<Escape>", self.close_all_menus, add="+")
        self.bind_all("<Button-1>", self._handle_global_click, add="+")

        self.bind("<Control-equal>", self.increase_font_size)
        self.bind("<Control-minus>", self.decrease_font_size)
        self.bind("<Control-f>", self.find_dialog)
        self.search_matches = []
        self.current_match_index = -1
        self.drag_item = None
        self.current_input_buffer = ""

        # Ensure the process exits cleanly when the window is closed
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.after(500, self._process_api_tcp_notifications)
        self.initialize_api_tcp_server()
        self.schedule_ephemeral_cleanup()

    def load_rag(self, path):
        """Load a ChromaDB RAG database from ``path``."""
        try:
            self.rag_manager.load(path)
        except Exception as exc:
            print(f"Failed to load RAG database: {exc}")

    def unload_rag(self):
        """Close any active RAG database."""
        self.rag_manager.close()

    def restart_app_with_db(self, db_path):
        """Restart the entire application with a new database path, safely across platforms."""
        global DB_PATH, RECENT_DBS, WINDOW_GEOMETRIES

        if not db_path:
            return

        # Normalize the DB path
        db_path = os.path.abspath(db_path)

        old_path = DB_PATH
        DB_PATH = db_path
        if db_path in RECENT_DBS:
            RECENT_DBS.remove(db_path)
        RECENT_DBS.insert(0, db_path)
        RECENT_DBS = RECENT_DBS[:5]
        save_recent_dbs(RECENT_DBS)

        WINDOW_GEOMETRIES[old_path] = self.get_window_state()
        save_window_geometries(WINDOW_GEOMETRIES)

        # Close any active RAG database before restarting
        if hasattr(self, "rag_manager"):
            self.rag_manager.close()

        # Schedule restart after UI finishes processing
        self.after(100, lambda: self._exec_new_process(db_path))

    def _exec_new_process(self, db_path):
        """Internal helper to restart the app with the given DB path."""
        python_exe = sys.executable
        script_path = os.path.abspath(__file__)
        
        if platform.system() == "Windows":
            # No shlex.quote on Windows — just wrap in double quotes if needed
            if " " in db_path:
                db_path = f'"{db_path}"'
            args = [python_exe, script_path, "--db", db_path]
        else:
            # Quote path safely for Unix
            args = [python_exe, script_path, "--db", db_path]

        print("Restarting with:", args)
        os.execl(python_exe, *args)

    def on_close(self):
        """Handle window close event and exit the process."""
        global WINDOW_GEOMETRIES
        # Ensure any RAG-related resources are released
        if hasattr(self, "rag_manager"):
            self.rag_manager.close()
        if getattr(self, "api_tcp_ephemeral_cleanup_job", None):
            try:
                self.after_cancel(self.api_tcp_ephemeral_cleanup_job)
            except Exception:
                pass
            self.api_tcp_ephemeral_cleanup_job = None
        self.stop_api_tcp_server(silent=True)
        WINDOW_GEOMETRIES[DB_PATH] = self.get_window_state()
        save_window_geometries(WINDOW_GEOMETRIES)
        self.destroy()
        sys.exit(0)

    def on_model_selected(self, event):
        if self.session_id:
            selected_model = self.model_var.get()
            update_session_model(self.session_id, selected_model)
        self.refresh_last_model_label()

    def refresh_model_dropdown(self, initial=False, preferred_model=None):
        models = get_available_models(self.current_server_config)
        if not models:
            models = ["gpt-3.5-turbo"]

        self.model_dropdown['values'] = models

        target_model = preferred_model
        if target_model and target_model in models:
            self.model_var.set(target_model)
        else:
            if initial:
                default_model = None
                if self.current_server_config:
                    default_model = self.current_server_config.get("default_model")
                if default_model not in models:
                    default_model = None
                target_model = default_model if default_model else (models[0] if models else None)
            else:
                current_model = self.model_var.get()
                target_model = current_model if current_model in models else None

            if not target_model and models:
                target_model = models[0]

            if target_model:
                self.model_var.set(target_model)

        resolved = self.model_var.get()
        self.refresh_last_model_label()
        return resolved

        if self.session_id:
            update_session_model(self.session_id, self.model_var.get())

    def refresh_server_dropdown(self, select_name=None):
        names = self.server_manager.list_server_names()
        self.server_dropdown['values'] = names

        desired_name = select_name or self.server_manager.get_active_server_name()
        if desired_name in names:
            self.server_var.set(desired_name)
        elif names:
            self.server_var.set(names[0])
            self.server_manager.set_active_server(names[0])
        else:
            self.server_var.set("")

        current_name = self.server_var.get()
        self.current_server_config = self.server_manager.get_server(current_name)
        set_current_server_config(self.current_server_config)

    def update_current_server_config(self, updates):
        if not self.current_server_config:
            return
        updated_config = dict(self.current_server_config)
        updated_config.update(updates)
        updated_config["original_name"] = self.current_server_config.get("name")
        saved_config = self.server_manager.add_or_update_server(updated_config)
        self.current_server_config = saved_config
        set_current_server_config(saved_config)

    def auto_summarize_enabled(self):
        if self.current_server_config is not None:
            return to_bool(self.current_server_config.get("auto_summarize"), default=True)
        return to_bool(get_setting("auto_summarize_chats", "True"), default=True)

    def on_server_selected(self, event=None):
        selected_name = self.server_var.get()
        server = self.server_manager.get_server(selected_name)
        if not server:
            self.current_server_config = None
            set_current_server_config(None)
            if self.session_id:
                update_session_server(self.session_id, None)
            messagebox.showerror("Server Unavailable", f"The server '{selected_name}' is not available.", parent=self)
            return

        self.current_server_config = server
        self.server_manager.set_active_server(selected_name)
        set_current_server_config(server)

        if self.session_id:
            update_session_server(self.session_id, selected_name)

        preferred_model = getattr(self, "_pending_preferred_model", None)
        self._pending_preferred_model = None
        resolved_model = self.refresh_model_dropdown(initial=False, preferred_model=preferred_model)

        if self.session_id and resolved_model:
            update_session_model(self.session_id, resolved_model)

        suppress_status = getattr(self, "_suppress_server_status_message", False)
        self._suppress_server_status_message = False
        if not suppress_status:
            self.show_status_message(f"Switched to server: {selected_name}")
        self.refresh_last_model_label()

    def add_server(self):
        dialog = ServerConfigDialog(self, "Add Server")
        if getattr(dialog, "result", None):
            try:
                new_server = self.server_manager.add_or_update_server(dialog.result)
            except ValueError as exc:
                messagebox.showerror("Server Exists", str(exc), parent=self)
                return
            self.refresh_server_dropdown(select_name=new_server["name"])
            self.refresh_model_dropdown(initial=True)
            self.show_status_message(f"Added server '{new_server['name']}'")

    def edit_current_server(self):
        current_name = self.server_var.get()
        current_server = self.server_manager.get_server(current_name)
        if not current_server:
            messagebox.showwarning("No Server", "No server is currently selected to edit.")
            return

        dialog = ServerConfigDialog(self, "Edit Server", server=current_server)
        if getattr(dialog, "result", None):
            try:
                updated_server = self.server_manager.add_or_update_server(dialog.result)
            except ValueError as exc:
                messagebox.showerror("Server Exists", str(exc), parent=self)
                return
            self.refresh_server_dropdown(select_name=updated_server["name"])
            self.refresh_model_dropdown(initial=False)
            self.show_status_message(f"Updated server '{updated_server['name']}'")

    def delete_current_server(self):
        current_name = self.server_var.get()
        if not current_name:
            messagebox.showwarning("No Server", "No server is currently selected to delete.")
            return

        if not messagebox.askyesno("Delete Server", f"Are you sure you want to delete '{current_name}'?"):
            return

        self.server_manager.delete_server(current_name)
        self.refresh_server_dropdown()
        self.refresh_model_dropdown(initial=True)
        if self.server_var.get():
            self.show_status_message(f"Switched to server: {self.server_var.get()}")
        else:
            self.show_status_message("Server deleted.")

    def on_session_list_motion(self, event):
        try:
            index = self.session_list.index(f"@{event.x},{event.y}")
            if index != self.last_hovered_index:
                self.last_hovered_index = index
                self.session_tooltip.hidetip()
                try:
                    session_name = self.session_list.get(index)
                    self.session_tooltip.showtip(session_name)
                except tk.TclError:
                    pass # Ignore errors when mouse is not over an item
        except tk.TclError:
            self.last_hovered_index = -1
            self.session_tooltip.hidetip()

    def on_button_press(self, event):
        item = self.session_tree.identify_row(event.y)
        self.drag_item = item
        if not item:
            return

        values = self.session_tree.item(item, "values")
        item_type = values[1] if values else None

        current_selection = set(self.session_tree.selection())
        shift_pressed = bool(event.state & 0x0001)
        ctrl_pressed = bool(event.state & 0x0004)

        if item in current_selection and not shift_pressed and not ctrl_pressed:
            self.session_tree.item(item, tags="drag_item")
            if item_type != 'folder':
                return "break"
            return None

        if item not in current_selection and not shift_pressed and not ctrl_pressed:
            self.session_tree.selection_set(item)
            current_selection = {item}
        self.session_tree.item(item, tags="drag_item")
        if not shift_pressed and not ctrl_pressed:
            if len(current_selection) > 1 or item_type != 'folder':
                return "break"

    def on_button_release(self, event):
        if not self.drag_item:
            return
        if not self.session_tree.exists(self.drag_item):
            self.drag_item = None
            return
            
        item_under_mouse = self.session_tree.identify_row(event.y)
        
        selected_items = [item for item in self.session_tree.selection() if self.session_tree.item(item, "values")]

        if item_under_mouse and item_under_mouse != self.drag_item:
            target_values = self.session_tree.item(item_under_mouse, "values")
            if target_values and target_values[1] == 'folder':
                target_id = target_values[0]
                target_name = self.session_tree.item(item_under_mouse, "text")
                moved = 0
                for item in selected_items:
                    if item == item_under_mouse:
                        continue
                    values = self.session_tree.item(item, "values")
                    if not values or values[1] != 'chat':
                        continue
                    self.session_tree.move(item, item_under_mouse, 'end')
                    self.update_item_parent(values[0], target_id)
                    moved += 1
                if moved:
                    self.show_status_message(f"Moved {moved} chat(s) to '{target_name}'.")
            else:
                # Dropped between items
                if len(selected_items) == 1 and self.drag_item:
                    parent = self.session_tree.parent(item_under_mouse)
                    index = self.session_tree.index(item_under_mouse)
                    self.session_tree.move(self.drag_item, parent, index)
                    drag_id = self.session_tree.item(self.drag_item, "values")[0]
                    parent_id = self.session_tree.item(parent, "values")[0] if parent else None
                    self.update_item_parent(drag_id, parent_id)
        elif not item_under_mouse:
            # Dropped in empty space, move to root
            moved = 0
            for item in selected_items:
                values = self.session_tree.item(item, "values")
                if not values:
                    continue
                self.session_tree.move(item, "", "end")
                self.update_item_parent(values[0], None)
                moved += 1
            if moved:
                self.show_status_message(f"Moved {moved} chat(s) to root.")

        self.clear_drop_indicator()
        if self.drag_item:
            self.session_tree.item(self.drag_item, tags="") # Clear drag indicator
        self.drag_item = None

    def move_item(self, event):
        if not self.drag_item:
            return
        
        # Clear previous indicators first
        self.clear_drop_indicator()
        
        item = self.session_tree.identify_row(event.y)
        
        if item and item != self.drag_item:
            if self.session_tree.item(item, "values")[1] == 'folder':
                self.session_tree.item(item, tags="drop_target")
        elif not item:
            # Not over any item, indicate root drop
            style_name = "Dark.RootDrop.Treeview" if self.theme.get() == "dark" else "RootDrop.Treeview"
            self.session_tree.configure(style=style_name)

    def clear_drop_indicator(self):
        # Restore original style
        style_name = "Dark.Treeview" if self.theme.get() == "dark" else "Treeview"
        self.session_tree.configure(style=style_name)
        # Clear target tag
        for item in self.session_tree.tag_has("drop_target"):
            self.session_tree.item(item, tags="")

    def create_folder_from_context(self):
        selection = self.session_tree.selection()
        parent_id = None
        if selection:
            selected_item = selection[0]
            # If selected item is a folder, new folder goes inside it
            if self.session_tree.item(selected_item, "values")[1] == 'folder':
                parent_id = self.session_tree.item(selected_item, "values")[0]
            else:
                # If it's a chat, new folder goes alongside it in the same parent
                parent_item = self.session_tree.parent(selected_item)
                if parent_item:
                    parent_id = self.session_tree.item(parent_item, "values")[0]
        
        self.new_folder(parent_id=parent_id)

    def clear_tags_recursively(self, item):
        for child in self.session_tree.get_children(item):
            self.session_tree.item(child, tags="")
            self.clear_tags_recursively(child)

    def update_item_parent(self, item_id, parent_id):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE sessions SET parent_id = ? WHERE id = ?", (parent_id, item_id))
        conn.commit()
        conn.close()

    def get_open_folders(self, item, open_folders):
        if self.session_tree.item(item, "open"):
            item_id = self.session_tree.item(item, "values")[0]
            open_folders.add(item_id)
        for child in self.session_tree.get_children(item):
            self.get_open_folders(child, open_folders)

    def hide_session_tooltip(self, event=None):
        self.session_tooltip.hidetip()
        self.last_hovered_index = -1

    def close_all_menus(self, event=None):
        for menu in getattr(self, "context_menus", []):
            try:
                menu.unpost()
            except tk.TclError:
                pass

    def _handle_global_click(self, event):
        if isinstance(event.widget, tk.Menu):
            return
        self.close_all_menus()
    
    def show_session_context_menu(self, event):
        self.close_all_menus()
        item = self.session_tree.identify_row(event.y)
        if not item:
            self.whitespace_context_menu.post(event.x_root, event.y_root)
            return

        current_selection = set(self.session_tree.selection())
        if item not in current_selection:
            self.session_tree.selection_set(item)
            current_selection = {item}
        item_type = self.session_tree.item(item, "values")[1]
        selection_types = {self.session_tree.item(i, "values")[1] for i in current_selection if self.session_tree.item(i, "values")}

        multiple = len(current_selection) > 1

        rag_enabled = getattr(self, "rag_enabled", True)

        if 'folder' in selection_types:
            self.session_context_menu.entryconfig("New Chat", state="normal")
            self.session_context_menu.entryconfig("Auto Rename Chat", state="disabled")
            self.session_context_menu.entryconfig("Summarize and Start New Chat", state="disabled")
            self.session_context_menu.entryconfig("Copy Chat", state="disabled")
            self.session_context_menu.entryconfig("Rename", state="normal" if not multiple else "disabled")
            self.session_context_menu.entryconfig("Manage Files", state="disabled")
            self.session_context_menu.entryconfig("Export...", state="normal" if not multiple else "disabled")
            self.session_context_menu.entryconfig("Import Chat...", state="normal" if not multiple else "disabled")
            self.session_context_menu.entryconfig("Import Folder...", state="normal" if not multiple else "disabled")
        else:
            self.session_context_menu.entryconfig("New Chat", state="disabled")
            self.session_context_menu.entryconfig("Auto Rename Chat", state="normal" if not multiple else "disabled")
            self.session_context_menu.entryconfig("Summarize and Start New Chat", state="normal" if not multiple else "disabled")
            self.session_context_menu.entryconfig("Copy Chat", state="normal" if not multiple else "disabled")
            self.session_context_menu.entryconfig("Rename", state="normal" if not multiple else "disabled")
            manage_state = "normal" if (rag_enabled and not multiple) else "disabled"
            self.session_context_menu.entryconfig("Manage Files", state=manage_state)
            self.session_context_menu.entryconfig("Export...", state="normal" if not multiple else "disabled")
            self.session_context_menu.entryconfig("Import Chat...", state="normal" if not multiple else "disabled")
            self.session_context_menu.entryconfig("Import Folder...", state="normal" if not multiple else "disabled")

        self.session_context_menu.post(event.x_root, event.y_root)

    def new_chat_in_folder(self):
        selection = self.session_tree.selection()
        if not selection:
            return
        
        selected_item = selection[0]
        item_type = self.session_tree.item(selected_item, "values")[1]
        if item_type == 'folder':
            parent_id = self.session_tree.item(selected_item, "values")[0]
            self.new_session(parent_id=parent_id)

    def rename_session(self):
        selection = self.session_tree.selection()
        if not selection:
            return

        selected_item = selection[0]
        session_id, _type = self.session_tree.item(selected_item, "values")
        session_id = int(session_id)
        old_name = self.session_tree.item(selected_item, "text")

        new_name = self._prompt_at_cursor("Rename", "Enter new name:", initial=old_name)
        if new_name and new_name != old_name:
            update_session_name(session_id, new_name)
            self.session_tree.item(selected_item, text=new_name)

            if self.session_id == session_id:
                self.session_name = new_name
                self.title(f"{APP_NAME} - {self.session_name}")

    def delete_session(self):
        selection = tuple(self.session_tree.selection())
        if not selection:
            return

        def remove_chat(session_id):
            if rag_functions:
                try:
                    files_to_delete = rag_functions['get_files_for_chat'](session_id)
                    if files_to_delete:
                        for file_path in files_to_delete:
                            rag_functions['delete_file_from_chat'](file_path, chat_id=session_id)
                        self.show_status_message(f"Deleted {len(files_to_delete)} associated files from RAG.")
                except Exception as e:
                    self.show_status_message(f"Error deleting RAG files: {e}")

            delete_session_and_messages(session_id)
            if self.session_id == session_id:
                self.session_id = None
                self.session_name = None
                self.last_model_used = None
                self.chat_history.configure(state="normal")
                self.chat_history.delete("1.0", tk.END)
                self.chat_history.configure(state="normal")
                self.update_input_widgets_state()
                self.refresh_last_model_label()

        chats = []
        folders = []
        for item in selection:
            values = self.session_tree.item(item, "values")
            if not values:
                continue
            session_id, item_type = values
            session_id = int(session_id)
            name = self.session_tree.item(item, "text")
            if item_type == 'folder':
                folders.append((item, session_id, name))
            else:
                chats.append((item, session_id, name))

        if chats and folders:
            messagebox.showinfo("Delete Items", "Please delete folders and chats separately.")
            return

        if folders:
            session_map, children_map = self._get_session_maps()
            selected_folder_ids = {session_id for _, session_id, _ in folders}

            def has_selected_ancestor(folder_id):
                record = session_map.get(folder_id)
                if not record:
                    return False
                parent = record[7]
                while parent is not None:
                    try:
                        parent_id = int(parent)
                    except (TypeError, ValueError):
                        break
                    if parent_id in selected_folder_ids:
                        return True
                    parent_record = session_map.get(parent_id)
                    if not parent_record:
                        break
                    parent = parent_record[7]
                return False

            pruned_folders = []
            for entry in folders:
                item, session_id, name = entry
                if has_selected_ancestor(session_id):
                    continue
                pruned_folders.append(entry)

            if not pruned_folders:
                return

            folder_infos = []
            total_chat_count = 0
            total_subfolder_count = 0

            for item, session_id, name in pruned_folders:
                descendants = self._collect_descendant_ids(session_id, children_map)
                chat_ids = [sid for sid in descendants if session_map.get(sid, (None,) * 9)[8] == 'chat']
                subfolder_ids = [sid for sid in descendants if session_map.get(sid, (None,) * 9)[8] == 'folder']
                folder_infos.append({
                    "item": item,
                    "session_id": session_id,
                    "name": name,
                    "descendants": descendants,
                    "chat_ids": chat_ids,
                    "subfolder_ids": subfolder_ids
                })
                total_chat_count += len(chat_ids)
                total_subfolder_count += len(subfolder_ids)

            if len(folder_infos) == 1:
                info = folder_infos[0]
                chat_count = len(info["chat_ids"])
                subfolder_count = len(info["subfolder_ids"])
                if subfolder_count:
                    prompt = (
                        f"Are you sure you want to delete folder '{info['name']}' "
                        f"and its {chat_count} chat(s) plus {subfolder_count} subfolder(s)?"
                    )
                else:
                    prompt = (
                        f"Are you sure you want to delete folder '{info['name']}' "
                        f"and its {chat_count} chat(s)?"
                    )
            else:
                prompt = (
                    f"Are you sure you want to delete {len(folder_infos)} folder(s) "
                    f"and all {total_chat_count} chat(s) contained within?"
                )
                if total_subfolder_count:
                    prompt += f" This includes {total_subfolder_count} nested subfolder(s)."

            if not prompt.endswith("?"):
                prompt = prompt.strip() + "?"

            if not self._confirm_at_cursor("Delete Folders", prompt):
                return

            processed_ids = set()
            for info in folder_infos:
                descendants = list(reversed(info["descendants"]))
                for desc_id in descendants:
                    if desc_id in processed_ids:
                        continue
                    record = session_map.get(desc_id)
                    if not record:
                        continue
                    if record[8] == 'chat':
                        remove_chat(desc_id)
                    else:
                        delete_session_and_messages(desc_id)
                    processed_ids.add(desc_id)

                if info["session_id"] not in processed_ids:
                    delete_session_and_messages(info["session_id"])
                    processed_ids.add(info["session_id"])

                if self.session_tree.exists(info["item"]):
                    self.session_tree.delete(info["item"])

            self.show_status_message(
                f"Deleted {len(folder_infos)} folder(s) and {total_chat_count} chat(s)."
            )
            return

        if chats:
            count = len(chats)
            if count == 1:
                prompt = f"Are you sure you want to delete session '{chats[0][2]}' and all its messages?"
            else:
                prompt = f"Are you sure you want to delete these {count} chats and all their messages?"
            if not self._confirm_at_cursor("Delete Chats", prompt):
                return

            for item, session_id, _ in chats:
                remove_chat(session_id)
                self.session_tree.delete(item)

            self.show_status_message(f"Deleted {count} chat(s).")

    def build_gui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Main PanedWindow (Left and Right Panels)
        self.main_paned_window = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.main_paned_window.grid(row=0, column=0, sticky="nsew", pady=10)

        # Left PanedWindow (Session List and Main Chat Area)
        self.left_paned_window = ttk.PanedWindow(self.main_paned_window, orient=tk.HORIZONTAL)
        self.main_paned_window.add(self.left_paned_window, weight=1)

        # --- Left Panel (Session List) ---
        self.left_frame = ttk.Frame(self.left_paned_window, width=200)
        self.left_paned_window.add(self.left_frame, weight=1)
        self.left_frame.columnconfigure(0, weight=1)
        self.left_frame.rowconfigure(6, weight=1)

        # --- Database Selection ---
        self.db_label = ttk.Label(self.left_frame, text="Database:")
        self.db_label.grid(row=0, column=0, sticky="w", padx=10, pady=(10, 5))
        self.db_var = tk.StringVar(value=DB_PATH)

        def choose_db_file():
            path = filedialog.askopenfilename(filetypes=[("DB files", "*.db"), ("All files", "*.*")])
            if path:
                self.db_var.set(path)

        all_paths = ['New...'] + RECENT_DBS + [DB_PATH]
        max_len = max(len(str(p)) for p in all_paths)
        self.db_dropdown = ttk.Combobox(self.left_frame, textvariable=self.db_var, state="readonly",
                                       width=max(30, min(80, max_len)))
        self.db_dropdown['values'] = ['New...'] + RECENT_DBS
        self.db_dropdown.grid(row=1, column=0, sticky="ew", padx=10)
        ttk.Button(self.left_frame, image=self.folder_icon, command=choose_db_file).grid(row=1, column=1, sticky="w", padx=5)

        create_tooltip(self.db_dropdown, lambda: self.db_var.get())

        def on_db_change(*args):
            selected = self.db_var.get()
            if selected == 'New...':
                new_path = filedialog.asksaveasfilename(defaultextension='.db',
                                                        filetypes=[('DB files', '*.db'), ('All files', '*.*')])
                if not new_path:
                    self.db_var.set(DB_PATH)
                    return
                try:
                    sqlite3.connect(new_path).close()
                except Exception as e:
                    messagebox.showerror('Error', f'Could not create database:\n{e}')
                    self.db_var.set(DB_PATH)
                    return
                self.restart_app_with_db(new_path)
            elif selected and selected != DB_PATH:
                self.restart_app_with_db(selected)

        self.db_var.trace_add('write', on_db_change)

        # --- Server Selection ---
        self.server_label = ttk.Label(self.left_frame, text="Select Server:")
        self.server_label.grid(row=2, column=0, sticky="w", padx=10, pady=(10, 5))

        self.server_dropdown = ttk.Combobox(self.left_frame, textvariable=self.server_var, state="readonly")
        self.server_dropdown.grid(row=3, column=0, sticky="ew", padx=10, pady=2)
        self.refresh_server_dropdown(select_name=self.server_var.get())
        self.server_dropdown.bind('<<ComboboxSelected>>', self.on_server_selected)

        self.server_manage_button = tk.Menubutton(self.left_frame, text="Manage", relief=tk.RAISED)
        self.server_manage_menu = tk.Menu(self.server_manage_button, tearoff=0)
        self.server_manage_menu.add_command(label="Add Server", command=self.add_server)
        self.server_manage_menu.add_command(label="Edit Current", command=self.edit_current_server)
        self.server_manage_menu.add_command(label="Delete Current", command=self.delete_current_server)
        self.server_manage_button["menu"] = self.server_manage_menu
        self.server_manage_button.grid(row=3, column=1, sticky="w", padx=5)

        # --- Model Selection ---
        self.model_label = ttk.Label(self.left_frame, text="Select Model:")
        self.model_label.grid(row=4, column=0, sticky="w", padx=10, pady=(10, 5))
        self.model_var = tk.StringVar()
        self.model_dropdown = ttk.Combobox(self.left_frame, textvariable=self.model_var, state="readonly")
        self.model_dropdown.grid(row=5, column=0, sticky="ew", padx=10, pady=2)
        self.model_dropdown.bind('<<ComboboxSelected>>', self.on_model_selected)
        self.refresh_model_dropdown(initial=True)

        self.session_tree = ttk.Treeview(self.left_frame, show="tree")
        self.session_tree.grid(row=6, column=0, sticky="nsew", padx=10, pady=10)
        self.session_tree.configure(selectmode="extended")
        self.session_tree.bind('<<TreeviewSelect>>', self.select_session)
        self.session_tree.bind('<Button-3>', self.show_session_context_menu)
        self.session_tree.bind("<B1-Motion>", self.move_item)
        self.session_tree.bind("<ButtonPress-1>", self.on_button_press, add="+")
        self.session_tree.bind("<ButtonRelease-1>", self.on_button_release)
        self.session_tree.bind("<F2>", lambda e: self.rename_session())

        self.session_tree.tag_configure("drop_target", background="lightblue")
        self.session_tree.tag_configure("drag_item", background="lightgrey")

        s = ttk.Style()
        s.configure("RootDrop.Treeview", fieldbackground="lightblue")
        s.configure("Dark.RootDrop.Treeview", fieldbackground="#004d00", foreground="white")
        s.map("Dark.RootDrop.Treeview", background=[('selected', '#4f5254')], foreground=[('selected', 'white')])

        self.session_context_menu = tk.Menu(self.session_tree, tearoff=0)
        self.session_context_menu.add_command(label="New Chat", command=self.new_chat_in_folder)
        self.session_context_menu.add_command(label="New Folder", command=self.create_folder_from_context)
        self.session_context_menu.add_command(label="Rename", command=self.rename_session)
        self.session_context_menu.add_command(label="Delete", command=self.delete_session)
        self.session_context_menu.add_separator()
        self.session_context_menu.add_command(label="Auto Rename Chat", command=self.auto_rename_selected_session)
        self.session_context_menu.add_command(label="Summarize and Start New Chat", command=self.summarize_and_start_new_chat)
        self.session_context_menu.add_command(label="Copy Chat", command=self.copy_selected_session)
        self.session_context_menu.add_command(label="Manage Files", command=self.manage_files_for_selection)
        self.session_context_menu.add_separator()
        self.session_context_menu.add_command(label="Export...", command=self.export_selected_item)
        self.session_context_menu.add_command(label="Import Chat...", command=self.import_chat_from_context)
        self.session_context_menu.add_command(label="Import Folder...", command=self.import_folder_from_context)

        self.whitespace_context_menu = tk.Menu(self.session_tree, tearoff=0)
        self.whitespace_context_menu.add_command(label="New Chat", command=lambda: self.new_session(parent_id=None))
        self.whitespace_context_menu.add_command(label="New Folder", command=lambda: self.new_folder(parent_id=None))
        self.whitespace_context_menu.add_separator()
        self.whitespace_context_menu.add_command(label="Import Chat...", command=lambda: self.import_chat(parent_id=None, expected_type="chat"))
        self.whitespace_context_menu.add_command(label="Import Folder...", command=lambda: self.import_chat(parent_id=None, expected_type="folder"))

        self.context_menus.extend([
            self.session_context_menu,
            self.whitespace_context_menu
        ])

        self.new_button = ttk.Button(self.left_frame, text="+ New", command=self.new_session)
        self.new_button.grid(row=7, column=0, sticky="ew", padx=10, pady=(0, 10))

        self.settings_button = ttk.Button(self.left_frame, text="Settings", command=self.open_settings)
        self.settings_button.grid(row=8, column=0, sticky="ew", padx=10, pady=(0, 10))

        # --- Main Chat Area ---
        self.main_frame = ttk.Frame(self.left_paned_window)
        self.left_paned_window.add(self.main_frame, weight=4)
        self.main_frame.rowconfigure(0, weight=1)
        self.main_frame.columnconfigure(0, weight=1)

        self.chat_history = ScrolledText(
            self.main_frame,
            wrap=tk.WORD,
            padx=10,
            selectbackground=self.selection_bg.get(),
            selectforeground=self.selection_fg.get()
        )
        self.chat_history.grid(row=0, column=0, sticky="nsew")
        self.chat_history.bind("<KeyPress>", self.chat_history_keypress)

        self.search_frame = ttk.Frame(self.main_frame)
        # self.search_frame.grid(row=1, column=0, sticky="ew", pady=2)
        self.search_entry = ttk.Entry(self.search_frame)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.search_entry.bind("<Return>", self.find_next)
        self.search_entry.bind("<Escape>", self.hide_search)
        self.next_button = ttk.Button(self.search_frame, text="Next", command=self.find_next)
        self.next_button.pack(side=tk.LEFT)
        self.prev_button = ttk.Button(self.search_frame, text="Prev", command=self.find_prev)
        self.prev_button.pack(side=tk.LEFT)
        self.close_button = ttk.Button(self.search_frame, text="X", command=self.hide_search)
        self.close_button.pack(side=tk.LEFT)
        self.search_frame.grid_remove() # Hide by default

        self.chat_history.tag_config("user_tag", foreground="#0078D7")
        self.chat_history.tag_config("assistant_tag", foreground="#008000")
        self.chat_history.tag_config("copy_link", foreground="blue", underline=True)
        self.chat_history.tag_bind("copy_link", "<Button-1>", self.copy_message_from_link)
        self.chat_history.tag_bind("copy_link", "<Enter>", lambda e: self.chat_history.config(cursor="hand2"))
        self.chat_history.tag_bind("copy_link", "<Leave>", lambda e: self.chat_history.config(cursor=""))

        self.chat_history.tag_config("h1", font=("TkDefaultFont", 16, "bold"), spacing3=5)
        self.chat_history.tag_config("h2", font=("TkDefaultFont", 14, "bold"), spacing3=5)
        self.chat_history.tag_config("h3", font=("TkDefaultFont", 12, "bold"), spacing3=5)
        self.chat_history.tag_config("bold", font=("TkDefaultFont", 10, "bold"))
        self.chat_history.tag_config("italic", font=("TkDefaultFont", 10, "italic"))
        self.chat_history.tag_config("code", font=("Courier", 10), background="#232323", foreground="white")
        self.chat_history.tag_config("pre", font=("Courier", 10), background="#232323", foreground="white", lmargin1=10, lmargin2=10, spacing1=5, spacing3=5)
        self.chat_history.tag_config("p", spacing1=2, spacing3=2)
        self.chat_history.tag_config("li", lmargin1=20, lmargin2=20)
        self.chat_history.tag_config("table", font=("Courier", 10), lmargin1=10, lmargin2=10)
        self.chat_history.tag_config("system_note", font=("TkDefaultFont", 10, "italic"), foreground="#6c737c")
        s.configure("System.TLabel", font=("TkDefaultFont", 9, "italic"), foreground="#6c737c")

        self.chat_history_menu = tk.Menu(self.chat_history, tearoff=0)
        self.chat_history_menu.add_command(label="Copy", command=self.copy_chat_selection)
        self.chat_history.bind("<Button-3>", self.show_chat_context_menu)

        self.selection_context_menu = tk.Menu(self.chat_history, tearoff=0)
        self.selection_context_menu.add_command(label="Copy", command=self.copy_chat_selection)
        self.selection_context_menu.add_separator()
        summarize_menu = tk.Menu(self.selection_context_menu, tearoff=0)
        summarize_menu.add_command(label="Summarize this text", command=lambda: self.process_selection("summarize"))
        summarize_menu.add_command(label="TL;DR version", command=lambda: self.process_selection("tldr"))
        self.selection_context_menu.add_cascade(label="Summarize", menu=summarize_menu)

        explain_menu = tk.Menu(self.selection_context_menu, tearoff=0)
        explain_menu.add_command(label="Explain this in simpler terms", command=lambda: self.process_selection("explain_simple"))
        explain_menu.add_command(label="Tell me more about this", command=lambda: self.process_selection("explain_more"))
        explain_menu.add_command(label="Add more detail/examples", command=lambda: self.process_selection("explain_detail"))
        self.selection_context_menu.add_cascade(label="Explain or Elaborate", menu=explain_menu)

        rewrite_menu = tk.Menu(self.selection_context_menu, tearoff=0)
        rewrite_menu.add_command(label="Rephrase this", command=lambda: self.process_selection("rewrite_rephrase"))
        rewrite_menu.add_command(label="Make this more formal", command=lambda: self.process_selection("rewrite_formal"))
        rewrite_menu.add_command(label="Make this more informal", command=lambda: self.process_selection("rewrite_informal"))
        rewrite_menu.add_command(label="Make this more professional", command=lambda: self.process_selection("rewrite_professional"))
        rewrite_menu.add_command(label="Improve grammar or style", command=lambda: self.process_selection("rewrite_improve"))
        self.selection_context_menu.add_cascade(label="Rewrite", menu=rewrite_menu)

        translate_menu = tk.Menu(self.selection_context_menu, tearoff=0)
        translate_menu.add_command(label="Translate to English", command=lambda: self.process_selection("translate_english"))
        translate_menu.add_command(label="Detect and translate", command=lambda: self.process_selection("translate_detect"))
        self.selection_context_menu.add_cascade(label="Translate", menu=translate_menu)

        analyze_menu = tk.Menu(self.selection_context_menu, tearoff=0)
        analyze_menu.add_command(label="Analyze sentiment or tone", command=lambda: self.process_selection("analyze_sentiment"))
        analyze_menu.add_command(label="Identify assumptions or bias", command=lambda: self.process_selection("analyze_bias"))
        analyze_menu.add_command(label="Classify the topic", command=lambda: self.process_selection("analyze_topic"))
        self.selection_context_menu.add_cascade(label="Analyze", menu=analyze_menu)

        ask_menu = tk.Menu(self.selection_context_menu, tearoff=0)
        ask_menu.add_command(label="Generate questions from this text", command=lambda: self.process_selection("ask_generate"))
        ask_menu.add_command(label="What questions can I ask about this?", command=lambda: self.process_selection("ask_what_questions"))
        self.selection_context_menu.add_cascade(label="Ask Questions", menu=ask_menu)

        extract_menu = tk.Menu(self.selection_context_menu, tearoff=0)
        extract_menu.add_command(label="Highlight key points", command=lambda: self.process_selection("extract_key_points"))
        extract_menu.add_command(label="Extract named entities (people, places, dates, etc.)", command=lambda: self.process_selection("extract_entities"))
        extract_menu.add_command(label="Pull out action items", command=lambda: self.process_selection("extract_action_items"))
        self.selection_context_menu.add_cascade(label="Extract Info", menu=extract_menu)

        expand_menu = tk.Menu(self.selection_context_menu, tearoff=0)
        expand_menu.add_command(label="Continue writing from here", command=lambda: self.process_selection("expand_continue"))
        expand_menu.add_command(label="Generate a follow-up paragraph/story/argument", command=lambda: self.process_selection("expand_follow_up"))
        self.selection_context_menu.add_cascade(label="Expand or Continue", menu=expand_menu)

        define_menu = tk.Menu(self.selection_context_menu, tearoff=0)
        define_menu.add_command(label="Define highlighted term(s)", command=lambda: self.process_selection("define_terms"))
        define_menu.add_command(label="Provide background or context", command=lambda: self.process_selection("define_context"))
        self.selection_context_menu.add_cascade(label="Define or Clarify", menu=define_menu)

        respond_menu = tk.Menu(self.selection_context_menu, tearoff=0)
        respond_menu.add_command(label="Write a reply or response", command=lambda: self.process_selection("respond_reply"))
        respond_menu.add_command(label="Start a discussion from this", command=lambda: self.process_selection("respond_discuss"))
        self.selection_context_menu.add_cascade(label="Respond or Interact", menu=respond_menu)

        self.context_menus.extend([
            self.chat_history_menu,
            self.selection_context_menu
        ])

        self.input_container_frame = ttk.Frame(self.main_frame)
        self.input_container_frame.grid(row=1, column=0, sticky="ew")
        self.input_container_frame.columnconfigure(0, weight=1)
        self.input_container_frame.rowconfigure(0, weight=0)
        self.input_container_frame.rowconfigure(1, weight=1)
        self.input_container_frame.rowconfigure(2, weight=0)

        self.last_model_label = ttk.Label(self.input_container_frame, text="", style="System.TLabel")
        self.last_model_label.grid(row=0, column=0, sticky="w", padx=5, pady=(4, 2))
        self.refresh_last_model_label()

        input_frame = ttk.Frame(self.input_container_frame)
        input_frame.grid(row=1, column=0, sticky="nsew")
        input_frame.columnconfigure(0, weight=1)

        self.input_box = tk.Text(
            input_frame,
            height=5,
            wrap=tk.WORD,
            selectbackground=self.selection_bg.get(),
            selectforeground=self.selection_fg.get()
        )
        self.input_box.grid(row=0, column=0, sticky="nsew")
        self.input_box.bind("<Control-Return>", self.send_message)
        self.input_box.bind("<Up>", self.history_up_wrapper)
        self.input_box.bind("<Down>", self.history_down_wrapper)

        button_frame = ttk.Frame(input_frame)
        button_frame.grid(row=0, column=1, sticky="ns")
        button_frame.rowconfigure(0, weight=1)
        button_frame.rowconfigure(1, weight=1)

        self.send_button = ttk.Button(button_frame, text="Send", command=self.send_message)
        self.send_button.grid(row=0, column=0, sticky="ew", padx=(5, 0))

        self.files_button = ttk.Button(button_frame, text="Files", command=self.open_files_dialog)
        self.files_button.grid(row=1, column=0, sticky="ew", padx=(5, 0), pady=(5, 0))

        # --- Right Panel (System Prompt) ---
        self.right_frame = ttk.Frame(self.main_paned_window, width=250)
        self.main_paned_window.add(self.right_frame)
        self.right_frame.columnconfigure(0, weight=1)
        self.right_frame.rowconfigure(4, weight=1)
        
        self.system_prompt_var = tk.StringVar()
        self.system_prompt_dropdown = ttk.Combobox(self.right_frame, textvariable=self.system_prompt_var, state="readonly")
        self.system_prompt_dropdown.grid(row=0, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
        self.system_prompt_dropdown.bind('<<ComboboxSelected>>', self.on_system_prompt_selected)

        self.system_prompt_title_label = ttk.Label(self.right_frame, text="Title:")
        self.system_prompt_title_label.grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.system_prompt_title_entry = ttk.Entry(self.right_frame)
        self.system_prompt_title_entry.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
        self.system_prompt_title_entry.bind("<KeyRelease>", self.on_prompt_modified)
       
        self.system_prompt_label = ttk.Label(self.right_frame, text="System Prompt:")
        self.system_prompt_label.grid(row=3, column=0, sticky="w", padx=5, pady=5)
        
        self.system_prompt_text = ScrolledText(self.right_frame, wrap=tk.WORD, height=10)
        self.system_prompt_text.grid(row=4, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)
        self.system_prompt_text.bind("<<Modified>>", self.on_prompt_modified)

        self.save_prompt_button = ttk.Button(self.right_frame, text="Save", command=self.save_current_system_prompt, state="disabled")
        self.save_prompt_button.grid(row=5, column=0, sticky="ew", padx=5, pady=5)

        self.delete_prompt_button = ttk.Button(self.right_frame, text="Delete", command=self.delete_current_system_prompt)
        self.delete_prompt_button.grid(row=5, column=1, sticky="ew", padx=5, pady=5)

        self.export_prompts_button = ttk.Button(self.right_frame, text="Export", command=self.export_system_prompts)
        self.export_prompts_button.grid(row=6, column=0, sticky="ew", padx=5, pady=5)

        self.import_prompts_button = ttk.Button(self.right_frame, text="Import", command=self.import_system_prompts)
        self.import_prompts_button.grid(row=6, column=1, sticky="ew", padx=5, pady=5)

        # --- Toggle Button for Right Panel ---
        style = ttk.Style()
        style.configure("Small.TButton", padding=1, font=('TkDefaultFont', 7))
        self.toggle_right_panel_button = ttk.Button(self, text="<", command=self.toggle_right_panel, style="Small.TButton")
        self.toggle_right_panel_button.place(relx=1.0, rely=0.0, x=-2, y=2, anchor="ne")

        # --- Status Bar ---
        self.status_bar = ttk.Label(self, text="", anchor=tk.W)
        self.status_bar.grid(row=1, column=0, sticky="ew")

    def apply_sash_position(self, sash_pos):
        if not hasattr(self, "main_paned_window"):
            return
        try:
            self.main_paned_window.sashpos(0, int(sash_pos))
        except Exception:
            pass

    def apply_default_sash(self, fraction=0.85):
        if not hasattr(self, "main_paned_window"):
            return
        total_width = self.main_paned_window.winfo_width()
        if total_width <= 1:
            self.after(100, self.apply_default_sash, fraction)
            return
        sash_pos = int(total_width * fraction)
        self.apply_sash_position(sash_pos)

    def get_window_state(self):
        state = {"geometry": self.geometry()}
        if hasattr(self, "main_paned_window"):
            try:
                state["sash"] = int(self.main_paned_window.sashpos(0))
            except Exception:
                pass
        return state

    def load_system_prompts_to_dropdown(self):
        self.system_prompts = get_system_prompts()
        prompt_titles = [p[1] for p in self.system_prompts]
        self.system_prompt_dropdown['values'] = ["New..."] + prompt_titles

    def on_system_prompt_selected(self, event):
        selected_title = self.system_prompt_var.get()
        if selected_title == "New...":
            self.system_prompt_title_entry.delete(0, tk.END)
            self.system_prompt_text.delete("1.0", tk.END)
            self.save_prompt_button.config(state="disabled")
            self.current_system_prompt_id = None
            if self.session_id:
                update_session_system_prompt_id(self.session_id, None)
            return

        for p_id, title, prompt in self.system_prompts:
            if title == selected_title:
                self.current_system_prompt_id = p_id
                self.system_prompt_title_entry.delete(0, tk.END)
                self.system_prompt_title_entry.insert(0, title)
                self.system_prompt_text.delete("1.0", tk.END)
                self.system_prompt_text.insert("1.0", prompt)
                self.save_prompt_button.config(state="disabled")
                self.system_prompt_text.edit_modified(False)
                if self.session_id:
                    update_session_system_prompt(self.session_id, prompt)
                    update_session_system_prompt_id(self.session_id, p_id)
                break

    def on_prompt_modified(self, event=None):
        self.save_prompt_button.config(state="normal")
        # For the text widget, we need to reset the modified flag after we've handled it
        if event and event.widget == self.system_prompt_text:
            event.widget.edit_modified(False)

    def save_current_system_prompt(self):
        title = self.system_prompt_title_entry.get()
        prompt = self.system_prompt_text.get("1.0", tk.END).strip()
        if not title or not prompt:
            self.show_status_message("Title and prompt cannot be empty.")
            return

        save_system_prompt(title, prompt)
        self.load_system_prompts_to_dropdown()
        self.system_prompt_var.set(title)
        self.show_status_message("Prompt saved")
        self.save_prompt_button.config(state="disabled")

    def delete_current_system_prompt(self):
        if hasattr(self, 'current_system_prompt_id'):
            if messagebox.askyesno("Delete System Prompt", "Are you sure you want to delete this system prompt?"):
                delete_system_prompt(self.current_system_prompt_id)
                self.load_system_prompts_to_dropdown()
                self.system_prompt_var.set("New...")
                self.system_prompt_title_entry.delete(0, tk.END)
                self.system_prompt_text.delete("1.0", tk.END)
                del self.current_system_prompt_id
        else:
            messagebox.showinfo("Delete System Prompt", "No system prompt selected to delete.")

    def toggle_system_prompt(self):
        if self.system_prompt_text.winfo_ismapped():
            self.system_prompt_text.grid_remove()
            self.system_prompt_label.grid_remove()
        else:
            self.system_prompt_text.grid()
            self.system_prompt_label.grid()

    def toggle_right_panel(self):
        if self.right_frame.winfo_ismapped():
            self.main_paned_window.forget(self.right_frame)
            self.toggle_right_panel_button.config(text="<")
        else:
            self.main_paned_window.add(self.right_frame)
            self.toggle_right_panel_button.config(text=">")

    def apply_theme(self):
        theme = self.theme.get()
        s = ttk.Style()
        if theme == "dark":
            if os.name == 'nt':
                s.theme_use('clam')
            self.configure(bg="#2b2b2b")
            # Left panel
            self.left_frame.configure(style="Dark.TFrame")
            self.model_label.configure(style="Dark.TLabel")
            self.session_tree.configure(style="Dark.Treeview")
            self.new_button.configure(style="Dark.TButton")
            self.settings_button.configure(style="Dark.TButton")
            # Main chat area
            self.main_frame.configure(style="Dark.TFrame")
            self.chat_history.configure(bg="#3c3f41", fg="white")
            self.input_container_frame.configure(style="Dark.TFrame")
            self.input_box.configure(bg="#4f5254", fg="white", insertbackground="white")
            self.send_button.configure(style="Dark.TButton")
            # Right panel
            self.right_frame.configure(style="Dark.TFrame")
            self.system_prompt_label.configure(style="Dark.TLabel")
            self.system_prompt_text.configure(bg="#3c3f41", fg="white", insertbackground="white")
            # Style configuration
            s.configure("Dark.TFrame", background="#2b2b2b")
            s.configure("Dark.TLabel", background="#2b2b2b", foreground="white")
            
            # Custom button styling for Windows dark mode
            if os.name == 'nt':
                if not os.path.isfile('transparent.png'):
                    img = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
                    img.save('transparent.png')
                img = tk.PhotoImage(file='transparent.png')
                s.element_create('Dark.TButton.photo', 'image', img, sticky='ew')
                s.layout('Dark.TButton', [('Dark.TButton.photo', {'children': [('Button.padding', {'children': [('Button.label', {'side': 'left', 'expand': 1})]})]})])

            s.configure("Dark.TButton", background="#4f5254", foreground="white", anchor="center")
            s.map("Dark.TButton", background=[('active', '#6f7274'), ('!disabled', '#4f5254')], foreground=[('!disabled', 'white')])
            s.configure("Dark.Treeview", background="#3c3f41", foreground="white", fieldbackground="#3c3f41")
            s.map("Dark.Treeview", background=[('selected', '#4f5254')], foreground=[('selected', 'white')])
        else: # Light mode
            self.configure(bg="#f0f0f0")
            # Left panel
            self.left_frame.configure(style="TFrame")
            self.model_label.configure(style="TLabel")
            self.session_tree.configure(style="Treeview")
            self.new_button.configure(style="TButton")
            self.settings_button.configure(style="TButton")
            # Main chat area
            self.main_frame.configure(style="TFrame")
            self.chat_history.configure(bg="white", fg="black")
            self.input_container_frame.configure(style="TFrame")
            self.input_box.configure(bg="white", fg="black", insertbackground="black")
            self.send_button.configure(style="TButton")
            # Right panel
            self.right_frame.configure(style="TFrame")
            self.system_prompt_label.configure(style="TLabel")
            self.system_prompt_text.configure(bg="white", fg="black", insertbackground="black")
            self.chat_history.tag_config("code", font=("Courier", 10), background="#f0f0f0", foreground="black")
            self.chat_history.tag_config("pre", font=("Courier", 10), background="#f0f0f0", foreground="black", lmargin1=10, lmargin2=10, spacing1=5, spacing3=5)
            s.configure("Treeview", background="white", foreground="black", fieldbackground="white")
            s.map("Treeview", background=[('selected', '#0078d7')], foreground=[('selected', 'white')])

        self.apply_selection_colors()

    def apply_font(self):
        font_name = self.chat_font.get()
        font_size = self.chat_font_size.get()
        try:
            custom_font = font.Font(family=font_name, size=font_size)
            self.chat_history.configure(font=custom_font)
            self.input_box.configure(font=custom_font)
        except tk.TclError:
            print(f"Font '{font_name}' not found, using default.")
            default_font = font.Font(family="TkDefaultFont", size=font_size)
            self.chat_history.configure(font=default_font)
            self.input_box.configure(font=default_font)

    def apply_ui_font(self):
        ui_font_name = self.ui_font.get()
        ui_font_size = self.ui_font_size.get()
        style = ttk.Style()
        style.configure("TLabel", font=(ui_font_name, ui_font_size))
        style.configure("TButton", font=(ui_font_name, ui_font_size))
        style.configure("TCombobox", font=(ui_font_name, ui_font_size))
        style.configure("Treeview", font=(ui_font_name, ui_font_size), rowheight=int(ui_font_size * 2.5))
        self.system_prompt_text.configure(font=(ui_font_name, ui_font_size))

    def apply_selection_colors(self):
        bg = self.selection_bg.get()
        fg = self.selection_fg.get()
        self.chat_history.configure(selectbackground=bg, selectforeground=fg)
        self.input_box.configure(selectbackground=bg, selectforeground=fg)

    def _coerce_tcp_port(self, value):
        try:
            port = int(value)
        except (TypeError, ValueError):
            port = DEFAULT_API_TCP_PORT
        if port < 1 or port > 65535:
            port = DEFAULT_API_TCP_PORT
        return port

    def _coerce_positive_int(self, value, default=1):
        try:
            converted = int(value)
        except (TypeError, ValueError):
            converted = default
        if converted <= 0:
            converted = default
        return converted

    def schedule_ephemeral_cleanup(self):
        if hasattr(self, "api_tcp_ephemeral_cleanup_job") and self.api_tcp_ephemeral_cleanup_job:
            self.after_cancel(self.api_tcp_ephemeral_cleanup_job)
            self.api_tcp_ephemeral_cleanup_job = None
        if not hasattr(self, "api_tcp_ephemeral_ttl_minutes"):
            return
        self.api_tcp_ephemeral_cleanup_job = self.after(60_000, self._cleanup_ephemeral_chats)

    def _cleanup_ephemeral_chats(self):
        self.api_tcp_ephemeral_cleanup_job = None
        ttl_seconds = max(1, getattr(self, "api_tcp_ephemeral_ttl_minutes", 60)) * 60
        now = time.time()
        expired_keys = []
        for key, session in list(self.api_tcp_ephemeral_chats.items()):
            last_access = session.get("last_access", now)
            if now - last_access >= ttl_seconds:
                expired_keys.append(key)
        if expired_keys:
            for key in expired_keys:
                self.api_tcp_ephemeral_chats.pop(key, None)
            self.refresh_ephemeral_stats_label()
            self.show_status_message(f"Expired {len(expired_keys)} ephemeral chat(s).", duration=3000)
        self.schedule_ephemeral_cleanup()

    def get_ephemeral_stats(self):
        sessions = len(self.api_tcp_ephemeral_chats)
        message_count = 0
        byte_count = 0
        for session in self.api_tcp_ephemeral_chats.values():
            messages = session.get("messages", [])
            message_count += len(messages)
            for msg in messages:
                if isinstance(msg, dict):
                    byte_count += len((msg.get("content") or ""))
        return sessions, message_count, byte_count

    def refresh_ephemeral_stats_label(self):
        stats_var = getattr(self, "_ephemeral_stats_var", None)
        if not stats_var:
            return
        sessions, message_count, byte_count = self.get_ephemeral_stats()
        stats_var.set(f"{sessions} session(s), {message_count} message(s), ~{format_bytes(byte_count)}")

    def clear_ephemeral_chats(self):
        cleared = len(self.api_tcp_ephemeral_chats)
        if cleared:
            self.api_tcp_ephemeral_chats.clear()
            self.refresh_ephemeral_stats_label()
            self.show_status_message(f"Cleared {cleared} ephemeral chat(s).", duration=3000)
        else:
            self.show_status_message("No ephemeral chats to clear.", duration=2500)
        self.schedule_ephemeral_cleanup()

    def get_api_folder_name(self):
        name = (self.api_tcp_folder_name or "").strip() or "API Chats"
        return name

    def reset_api_folder_cache(self):
        self.api_tcp_folder_id = None

    def get_or_create_api_folder(self):
        target_name = self.get_api_folder_name()

        if getattr(self, "api_tcp_folder_id", None):
            record = get_session_by_id(self.api_tcp_folder_id)
            if record and record[8] == 'folder' and record[1] == target_name:
                return self.api_tcp_folder_id, False
            self.api_tcp_folder_id = None

        for record in get_sessions():
            if record[8] == 'folder' and record[1] == target_name:
                self.api_tcp_folder_id = record[0]
                return self.api_tcp_folder_id, False

        folder_id = create_session(
            target_name,
            model='gpt-3.5-turbo',
            system_prompt='',
            type='folder',
            parent_id=None,
            system_prompt_id=None,
            last_model_used='gpt-3.5-turbo',
            server_name=None
        )
        self.api_tcp_folder_id = folder_id
        return folder_id, True

    def get_cached_server_models(self, server_config, force=False):
        if not server_config:
            return []

        key = (
            server_config.get("name"),
            server_config.get("base_url"),
            server_config.get("models_path"),
        )
        now = time.time()
        ttl = self.api_server_cache_ttl

        with self.api_server_cache_lock:
            entry = self.api_server_models_cache.get(key)
            if entry and not force and (now - entry.get("timestamp", 0)) < ttl:
                return list(entry.get("models", []))

        try:
            models = list(get_available_models(server_config))
        except Exception as exc:
            print(f"Failed to retrieve models for server {server_config.get('name')}: {exc}")
            models = []

        if not models:
            fallback_model = server_config.get("default_model") or "gpt-3.5-turbo"
            models = [fallback_model]

        with self.api_server_cache_lock:
            self.api_server_models_cache[key] = {
                "timestamp": now,
                "models": list(models),
            }

        return models

    def _process_api_tcp_notifications(self):
        try:
            while True:
                notice = self.api_tcp_notifications.get_nowait()
                if not notice:
                    continue
                if notice.get("refresh_ephemeral"):
                    self.refresh_ephemeral_stats_label()
                if notice.get("refresh_sessions"):
                    self.load_sessions(set_selection=False)
                session_id = notice.get("session_id")
                new_chat = bool(notice.get("new_chat"))
                if new_chat:
                    self.load_sessions(set_selection=False)
                if session_id and self.session_id == session_id:
                    self.load_chat_history()
                    self.refresh_last_model_label()
        except queue.Empty:
            pass
        finally:
            if self.winfo_exists():
                self.after(500, self._process_api_tcp_notifications)

    def initialize_api_tcp_server(self):
        if self.api_tcp_enabled:
            self.start_api_tcp_server(silent=True)

    def start_api_tcp_server(self, *, silent=False):
        if self.api_tcp_server_thread and self.api_tcp_server_thread.is_alive():
            if not silent:
                self.show_status_message(
                    f"API TCP server already running on {self.api_tcp_host}:{self.api_tcp_port}",
                    duration=2500,
                )
            return True
        port = self._coerce_tcp_port(self.api_tcp_port)
        self.api_tcp_port = port
        save_setting("api_tcp_port", port)
        host = self.api_tcp_host or DEFAULT_API_TCP_HOST
        self.api_tcp_host = host
        save_setting("api_tcp_host", host)
        try:
            self.api_tcp_server_thread = APIChatTCPServer(self, host=host, port=port)
            self.api_tcp_server_thread.start()
            if not silent:
                self.show_status_message(
                    f"API TCP server listening on {host}:{port}",
                    duration=2500,
                )
            return True
        except Exception as exc:
            self.api_tcp_server_thread = None
            self.api_tcp_enabled = False
            save_setting("enable_api_tcp_server", "False")
            self.show_status_message(f"Failed to start API TCP server: {exc}", duration=5000)
            return False

    def stop_api_tcp_server(self, *, silent=False):
        if self.api_tcp_server_thread:
            self.api_tcp_server_thread.stop()
            self.api_tcp_server_thread.join(timeout=1.5)
            self.api_tcp_server_thread = None
            if not silent:
                self.show_status_message("API TCP server stopped", duration=2500)

    def restart_api_tcp_server(self, *, silent=False):
        self.stop_api_tcp_server(silent=True)
        if self.api_tcp_enabled:
            return self.start_api_tcp_server(silent=silent)
        return True

    def on_api_tcp_server_error(self, exc):
        self.api_tcp_server_thread = None
        if self.api_tcp_enabled:
            self.api_tcp_enabled = False
            save_setting("enable_api_tcp_server", "False")
        self.show_status_message(f"API TCP server error: {exc}", duration=6000)

    def handle_api_tcp_command(self, command):
        normalized = command.strip().lower()
        if normalized == "/models":
            return {"ok": True, "data": self.describe_api_tcp_servers()}
        return {"ok": False, "error": f"Unknown command '{command.strip()}'"}

    def describe_api_tcp_servers(self):
        servers_info = []
        for config in self.server_manager.load_servers():
            models = self.get_cached_server_models(config)
            servers_info.append({
                "name": config.get("name"),
                "base_url": config.get("base_url"),
                "models": models,
            })

        listening = bool(self.api_tcp_server_thread and self.api_tcp_server_thread.is_alive())
        default_server = self.api_tcp_default_server or self.server_manager.get_active_server_name()
        if not default_server and self.server_configs:
            default_server = self.server_configs[0].get("name")
        if not default_server and servers_info:
            default_server = servers_info[0].get("name")

        default_model = self.api_tcp_default_model
        if not default_model and self.current_server_config:
            default_model = self.current_server_config.get("default_model")
        if not default_model and servers_info:
            for entry in servers_info:
                models = entry.get("models") or []
                if models:
                    default_model = models[0]
                    break
        default_server = default_server or "OpenAI"
        default_model = default_model or "gpt-3.5-turbo"

        return {
            "listening": listening,
            "port": self.api_tcp_port,
            "default_server": default_server,
            "default_model": default_model,
            "create_ui_chats": self.api_tcp_create_ui_chats,
            "ui_folder": self.get_api_folder_name() if self.api_tcp_create_ui_chats else None,
            "servers": servers_info,
        }

    def process_api_tcp_payload(self, payload):
        if not isinstance(payload, dict):
            return {"ok": False, "error": "Payload must be a JSON object."}

        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            return {"ok": False, "error": "Payload must include a non-empty 'message' string."}
        message = message.strip()

        requested_server = payload.get("server")
        requested_model = payload.get("model")
        chat_id = payload.get("chat_id")
        system_prompt = payload.get("system_prompt")
        if system_prompt is not None and not isinstance(system_prompt, str):
            system_prompt = str(system_prompt)
        title_hint = payload.get("name") or payload.get("title")
        stream_pref = payload.get("stream")
        stream_responses = to_bool(stream_pref, default=True)

        server_name = requested_server or self.api_tcp_default_server
        if not server_name and self.current_server_config:
            server_name = self.current_server_config.get("name")
        if not server_name:
            server_name = self.server_manager.get_active_server_name()
        if not server_name:
            available = self.server_manager.list_server_names()
            server_name = available[0] if available else None
        if not server_name:
            return {"ok": False, "error": "No server is configured for API chats."}

        server_config = self.server_manager.get_server(server_name)
        if not server_config:
            if requested_server:
                return {"ok": False, "error": f"Unknown server '{requested_server}'."}
            available = self.server_manager.list_server_names()
            if not available:
                return {"ok": False, "error": "No server configuration available."}
            server_name = available[0]
            server_config = self.server_manager.get_server(server_name)

        model = requested_model or self.api_tcp_default_model or server_config.get("default_model") or "gpt-3.5-turbo"
        current_time = time.time()

        if self.api_tcp_create_ui_chats:
            try:
                session_id = int(chat_id) if chat_id is not None else None
            except (TypeError, ValueError):
                return {"ok": False, "error": "chat_id must be an integer when persistence is enabled."}

            is_new_chat = False
            session_name = None
            previous_model = model
            session_prompt = system_prompt or ""
            if session_id is not None:
                session_record = get_session_by_id(session_id)
                if not session_record:
                    return {"ok": False, "error": f"Chat id {session_id} not found."}
                session_name = session_record[1]
                stored_prompt = session_record[5] or ""
                previous_model = session_record[4] or session_record[2] or model
                if system_prompt is None:
                    session_prompt = stored_prompt
                else:
                    update_session_system_prompt(session_id, session_prompt)
            else:
                folder_id, folder_created = self.get_or_create_api_folder()
                if folder_created:
                    self.api_tcp_notifications.put({"refresh_sessions": True})

                suffix_raw = (title_hint or uuid.uuid4().hex[:8].upper())
                suffix = suffix_raw.strip() or uuid.uuid4().hex[:8].upper()
                session_name = suffix
                if not session_name.lower().startswith("api:"):
                    session_name = f"API: {session_name}"
                session_prompt = system_prompt or ""
                session_id = create_session(
                    session_name,
                    model,
                    session_prompt,
                    type='chat',
                    parent_id=folder_id,
                    system_prompt_id=None,
                    last_model_used=model,
                    server_name=server_name
                )
                is_new_chat = True
                previous_model = model

            save_message(session_id, "user", message)
            save_input_history(session_id, message)
            update_session_server(session_id, server_name)
            update_session_model(session_id, model)

            db_messages = get_messages(session_id)
            message_blocks = [{"role": role, "content": content} for role, content in db_messages]
            if session_prompt:
                message_blocks.insert(0, {"role": "system", "content": session_prompt})

            try:
                assistant_reply = send_to_api(
                    session_name,
                    message_blocks,
                    model,
                    session_id,
                    server_config=server_config,
                    widget=None,
                    save_message_to_db=True,
                    stream=stream_responses
                )
            except Exception as exc:
                return {"ok": False, "error": f"API request failed: {exc}"}

            update_session_last_model_used(session_id, model)

            self.api_tcp_notifications.put({"session_id": session_id, "new_chat": is_new_chat})
            if self.session_id == session_id:
                self.last_model_used = model

            return {
                "ok": True,
                "chat_id": session_id,
                "chat_name": session_name,
                "model": model,
                "last_model_used": previous_model,
                "message": assistant_reply,
                "server": server_name,
                "new_chat": is_new_chat
            }

        # Ephemeral mode (no UI persistence)
        ephemeral_id = str(chat_id) if chat_id else uuid.uuid4().hex
        session = self.api_tcp_ephemeral_chats.get(ephemeral_id)
        is_new_chat = False
        if session is None:
            session = {
                "messages": [],
                "server": server_name,
                "model": model,
                "last_model_used": model,
                "system_prompt": system_prompt or "",
                "created_at": current_time,
                "last_access": current_time,
            }
            self.api_tcp_ephemeral_chats[ephemeral_id] = session
            is_new_chat = True
        else:
            if system_prompt is not None:
                session["system_prompt"] = system_prompt or ""
            if requested_server:
                session["server"] = server_name
            session["last_access"] = current_time
            session.setdefault("created_at", current_time)

        previous_model = session.get("model", model)
        history = list(session.get("messages", []))
        history.append({"role": "user", "content": message})

        message_blocks = list(history)
        if session.get("system_prompt"):
            message_blocks.insert(0, {"role": "system", "content": session["system_prompt"]})

        try:
            assistant_reply = send_to_api(
                f"API Chat {ephemeral_id[:8]}",
                message_blocks,
                model,
                current_session_id=0,
                server_config=server_config,
                widget=None,
                save_message_to_db=False,
                stream=stream_responses
            )
        except Exception as exc:
            return {"ok": False, "error": f"API request failed: {exc}"}

        history.append({"role": "assistant", "content": assistant_reply})
        session["messages"] = history
        session["last_model_used"] = previous_model
        session["model"] = model
        session["server"] = server_name
        session["last_access"] = current_time

        self.api_tcp_notifications.put({"refresh_ephemeral": True})
        return {
            "ok": True,
            "chat_id": ephemeral_id,
            "model": model,
            "last_model_used": previous_model,
            "message": assistant_reply,
            "server": server_name,
            "new_chat": is_new_chat,
            "ephemeral": True
        }

    def open_settings(self):
        settings_win = tk.Toplevel(self)
        settings_win.title("Settings")
        settings_win.geometry("900x680")
        settings_win.grid_columnconfigure(0, weight=1, uniform="settings")
        settings_win.grid_columnconfigure(1, weight=1, uniform="settings")
        settings_win.grid_rowconfigure(0, weight=1)

        general_frame = ttk.Frame(settings_win)
        general_frame.grid(row=0, column=0, sticky="nsew", padx=15, pady=15)
        general_frame.grid_columnconfigure(0, weight=1)
        general_frame.grid_columnconfigure(1, weight=1)

        advanced_frame = ttk.Frame(settings_win)
        advanced_frame.grid(row=0, column=1, sticky="nsew", padx=15, pady=15)
        advanced_frame.grid_columnconfigure(0, weight=1)
        advanced_frame.grid_columnconfigure(1, weight=1)

        font_families = sorted(font.families())

        def apply_theme_styles():
            bg = "#2b2b2b" if self.theme.get() == "dark" else "#f0f0f0"
            settings_win.configure(bg=bg)

            def update_styles(widget):
                if isinstance(widget, (ttk.Label, ttk.Radiobutton)):
                    widget.configure(style="Dark.TLabel" if self.theme.get() == "dark" else "TLabel")
                for child in widget.winfo_children():
                    update_styles(child)

            update_styles(settings_win)

        def on_theme_change():
            save_setting("theme", self.theme.get())
            self.apply_theme()
            apply_theme_styles()

        general_row = 0
        ttk.Label(general_frame, text="Theme:").grid(row=general_row, column=0, columnspan=2, sticky="w", pady=(0, 5))
        general_row += 1

        light_radio = ttk.Radiobutton(general_frame, text="Light", variable=self.theme, value="light", command=on_theme_change)
        light_radio.grid(row=general_row, column=0, sticky="w", padx=(0, 10))
        dark_radio = ttk.Radiobutton(general_frame, text="Dark", variable=self.theme, value="dark", command=on_theme_change)
        dark_radio.grid(row=general_row, column=1, sticky="w")
        general_row += 1

        ttk.Label(general_frame, text="Default Model:").grid(row=general_row, column=0, columnspan=2, sticky="w", pady=(10, 5))
        general_row += 1

        auto_summarize_setting = None
        if self.current_server_config:
            auto_summarize_setting = self.current_server_config.get("auto_summarize")
        if auto_summarize_setting is None:
            auto_summarize_setting = to_bool(get_setting("auto_summarize_chats", "True"), default=True)
        auto_summarize_var = tk.BooleanVar(value=to_bool(auto_summarize_setting, default=True))

        def on_auto_summarize_change():
            value = auto_summarize_var.get()
            save_setting("auto_summarize_chats", "True" if value else "False")
            self.update_current_server_config({"auto_summarize": value})
            status_text = "Auto summarize enabled" if value else "Auto summarize disabled"
            self.show_status_message(status_text)

        ttk.Checkbutton(
            general_frame,
            text="Auto summarize chats?",
            variable=auto_summarize_var,
            command=on_auto_summarize_change
        ).grid(row=general_row, column=0, columnspan=2, sticky="w")
        general_row += 1

        ttk.Label(general_frame, text="Chat Font:").grid(row=general_row, column=0, columnspan=2, sticky="w", pady=(10, 5))

        def on_font_change(*args):
            save_setting("chat_font", self.chat_font.get())
            self.apply_font()

        general_row += 1
        font_dropdown = ttk.Combobox(general_frame, textvariable=self.chat_font, state="readonly", values=font_families)
        font_dropdown.grid(row=general_row, column=0, columnspan=2, sticky="ew")
        self.chat_font.trace_add("write", on_font_change)

        ttk.Label(general_frame, text="Chat Font Size:").grid(row=general_row + 1, column=0, columnspan=2, sticky="w", pady=(10, 5))

        def on_font_size_change(*args):
            save_setting("chat_font_size", self.chat_font_size.get())
            self.apply_font()

        general_row += 2
        font_size_spinbox = ttk.Spinbox(general_frame, from_=8, to=72, textvariable=self.chat_font_size, command=on_font_size_change)
        font_size_spinbox.grid(row=general_row, column=0, columnspan=2, sticky="ew")
        self.chat_font_size.trace_add("write", on_font_size_change)

        ttk.Label(general_frame, text="UI Font:").grid(row=general_row + 1, column=0, columnspan=2, sticky="w", pady=(10, 5))

        def on_ui_font_change(*args):
            save_setting("ui_font", self.ui_font.get())
            self.apply_ui_font()

        general_row += 2
        ui_font_dropdown = ttk.Combobox(general_frame, textvariable=self.ui_font, state="readonly", values=font_families)
        ui_font_dropdown.grid(row=general_row, column=0, columnspan=2, sticky="ew")
        self.ui_font.trace_add("write", on_ui_font_change)

        ttk.Label(general_frame, text="UI Font Size:").grid(row=general_row + 1, column=0, columnspan=2, sticky="w", pady=(10, 5))

        def on_ui_font_size_change(*args):
            save_setting("ui_font_size", self.ui_font_size.get())
            self.apply_ui_font()

        general_row += 2
        ui_font_size_spinbox = ttk.Spinbox(general_frame, from_=8, to=72, textvariable=self.ui_font_size, command=on_ui_font_size_change)
        ui_font_size_spinbox.grid(row=general_row, column=0, columnspan=2, sticky="ew")
        self.ui_font_size.trace_add("write", on_ui_font_size_change)

        ttk.Label(general_frame, text="Selection Background:").grid(row=general_row + 1, column=0, columnspan=2, sticky="w", pady=(10, 5))

        def choose_sel_bg():
            color = colorchooser.askcolor(initialcolor=self.selection_bg.get())[1]
            if color:
                self.selection_bg.set(color)

        general_row += 2
        bg_frame = ttk.Frame(general_frame)
        bg_frame.grid(row=general_row, column=0, columnspan=2, sticky="ew")
        bg_frame.columnconfigure(0, weight=1)
        ttk.Entry(bg_frame, textvariable=self.selection_bg).grid(row=0, column=0, sticky="ew")
        ttk.Button(bg_frame, text="Pick", command=choose_sel_bg).grid(row=0, column=1, padx=(5, 0))

        ttk.Label(general_frame, text="Selection Foreground:").grid(row=general_row + 1, column=0, columnspan=2, sticky="w", pady=(10, 5))

        def choose_sel_fg():
            color = colorchooser.askcolor(initialcolor=self.selection_fg.get())[1]
            if color:
                self.selection_fg.set(color)

        general_row += 2
        fg_frame = ttk.Frame(general_frame)
        fg_frame.grid(row=general_row, column=0, columnspan=2, sticky="ew")
        fg_frame.columnconfigure(0, weight=1)
        ttk.Entry(fg_frame, textvariable=self.selection_fg).grid(row=0, column=0, sticky="ew")
        ttk.Button(fg_frame, text="Pick", command=choose_sel_fg).grid(row=0, column=1, padx=(5, 0))

        def on_selection_color_change(*args):
            save_setting("selection_bg", self.selection_bg.get())
            save_setting("selection_fg", self.selection_fg.get())
            self.apply_selection_colors()

        self.selection_bg.trace_add("write", on_selection_color_change)
        self.selection_fg.trace_add("write", on_selection_color_change)

        ttk.Label(general_frame, text="Enable RAG (requires restart):").grid(row=general_row + 1, column=0, columnspan=2, sticky="w", pady=(10, 5))
        rag_var = tk.BooleanVar(value=self.rag_enabled)

        def on_rag_toggle():
            save_setting("enable_rag", rag_var.get())
            messagebox.showinfo("Restart Required", "Please restart the application for the RAG setting to take effect.", parent=settings_win)

        general_row += 2
        ttk.Checkbutton(general_frame, variable=rag_var, command=on_rag_toggle).grid(row=general_row, column=0, columnspan=2, sticky="w")

        ttk.Label(general_frame, text="Validate SSL certificates for URL extraction:").grid(row=general_row + 1, column=0, columnspan=2, sticky="w", pady=(10, 5))
        url_ssl_var = tk.BooleanVar(value=to_bool(get_setting("validate_url_ssl", "True"), default=True))

        def on_url_ssl_toggle():
            save_setting("validate_url_ssl", url_ssl_var.get())

        general_row += 2
        ttk.Checkbutton(general_frame, variable=url_ssl_var, command=on_url_ssl_toggle).grid(row=general_row, column=0, columnspan=2, sticky="w")
        self.validate_url_ssl_var = url_ssl_var

        # --- Advanced / API panel ---
        advanced_row = 0
        ttk.Label(advanced_frame, text="API TCP Bridge:").grid(row=advanced_row, column=0, columnspan=2, sticky="w")
        advanced_row += 1

        api_tcp_enabled_var = tk.BooleanVar(value=self.api_tcp_enabled)
        api_tcp_port_var = tk.StringVar(value=str(self.api_tcp_port))

        def apply_api_tcp_port():
            raw_value = (api_tcp_port_var.get() or "").strip()
            new_port = self._coerce_tcp_port(raw_value or DEFAULT_API_TCP_PORT)
            if str(new_port) != raw_value:
                api_tcp_port_var.set(str(new_port))
            if new_port != self.api_tcp_port:
                self.api_tcp_port = new_port
                save_setting("api_tcp_port", new_port)
                if self.api_tcp_enabled:
                    if self.restart_api_tcp_server(silent=True):
                        self.show_status_message(f"API TCP server listening on port {new_port}", duration=2500)
                    else:
                        self.show_status_message("Failed to restart API TCP server; disabling.", duration=4000)
                        api_tcp_enabled_var.set(False)
                        self.api_tcp_enabled = False
                        save_setting("enable_api_tcp_server", "False")

        def on_api_tcp_toggle():
            new_value = api_tcp_enabled_var.get()
            self.api_tcp_enabled = new_value
            save_setting("enable_api_tcp_server", "True" if new_value else "False")
            if new_value:
                apply_api_tcp_port()
                if not self.start_api_tcp_server():
                    api_tcp_enabled_var.set(False)
                    self.api_tcp_enabled = False
                    save_setting("enable_api_tcp_server", "False")
            else:
                self.stop_api_tcp_server()

        ttk.Checkbutton(
            advanced_frame,
            text="Enable API TCP server",
            variable=api_tcp_enabled_var,
            command=on_api_tcp_toggle
        ).grid(row=advanced_row, column=0, columnspan=2, sticky="w", pady=(0, 10))
        advanced_row += 1

        ttk.Label(advanced_frame, text="TCP Port:").grid(row=advanced_row, column=0, sticky="w")
        port_entry = ttk.Entry(advanced_frame, textvariable=api_tcp_port_var, width=12)
        port_entry.grid(row=advanced_row, column=1, sticky="w")
        port_entry.bind("<FocusOut>", lambda event: apply_api_tcp_port())
        port_entry.bind("<Return>", lambda event: (apply_api_tcp_port(), "break"))
        advanced_row += 1

        api_tcp_localhost_var = tk.BooleanVar(value=(self.api_tcp_host == "127.0.0.1"))

        def on_api_tcp_host_toggle():
            bind_local = api_tcp_localhost_var.get()
            new_host = "127.0.0.1" if bind_local else "0.0.0.0"
            if new_host == self.api_tcp_host:
                return
            self.api_tcp_host = new_host
            save_setting("api_tcp_host", new_host)
            scope_desc = "localhost only" if bind_local else "all interfaces"
            self.show_status_message(f"API TCP server binding to {scope_desc}")
            if self.api_tcp_enabled:
                if not self.restart_api_tcp_server(silent=True):
                    self.show_status_message("Failed to restart API TCP server; disabling.", duration=4000)
                    api_tcp_enabled_var.set(False)
                    self.api_tcp_enabled = False
                    save_setting("enable_api_tcp_server", "False")

        ttk.Checkbutton(
            advanced_frame,
            text="Bind to localhost only",
            variable=api_tcp_localhost_var,
            command=on_api_tcp_host_toggle
        ).grid(row=advanced_row, column=0, columnspan=2, sticky="w")
        advanced_row += 1

        server_names = self.server_manager.list_server_names()
        initial_api_server = self.api_tcp_default_server if self.api_tcp_default_server in server_names else ""
        if not initial_api_server:
            if self.current_server_config:
                initial_api_server = self.current_server_config.get("name")
            elif server_names:
                initial_api_server = server_names[0]
        api_tcp_server_var = tk.StringVar(value=initial_api_server or "")
        if initial_api_server and initial_api_server != self.api_tcp_default_server:
            self.api_tcp_default_server = initial_api_server
            save_setting("api_tcp_default_server", initial_api_server)

        ttk.Label(advanced_frame, text="Default Server:").grid(row=advanced_row, column=0, sticky="w")
        server_combo = ttk.Combobox(advanced_frame, textvariable=api_tcp_server_var, state="readonly", values=server_names)
        server_combo.grid(row=advanced_row, column=1, sticky="ew")
        advanced_row += 1

        api_tcp_model_var = tk.StringVar(value=self.api_tcp_default_model or "")
        ttk.Label(advanced_frame, text="Default Model:").grid(row=advanced_row, column=0, sticky="w")
        model_combo = ttk.Combobox(advanced_frame, textvariable=api_tcp_model_var, state="readonly", values=[])
        model_combo.grid(row=advanced_row, column=1, sticky="ew")
        advanced_row += 1

        def on_api_tcp_model_change(*_):
            selected = api_tcp_model_var.get()
            if selected != self.api_tcp_default_model:
                self.api_tcp_default_model = selected
                save_setting("api_tcp_default_model", selected)

        api_tcp_model_var.trace_add("write", on_api_tcp_model_change)

        def refresh_api_tcp_model_options(server_name):
            server_config = self.server_manager.get_server(server_name) if server_name else None
            models = []
            if server_config:
                try:
                    models = get_available_models(server_config)
                except Exception as exc:
                    print(f"Failed to fetch models for {server_name}: {exc}")
                    models = []
            model_combo['values'] = models
            if models:
                preferred = api_tcp_model_var.get() or server_config.get("default_model") or models[0]
                if preferred not in models:
                    preferred = server_config.get("default_model") or models[0]
                api_tcp_model_var.set(preferred)
            else:
                api_tcp_model_var.set("")

        def on_api_tcp_server_change(event=None):
            selected = api_tcp_server_var.get()
            if selected != self.api_tcp_default_server:
                self.api_tcp_default_server = selected
                save_setting("api_tcp_default_server", selected)
            refresh_api_tcp_model_options(selected)

        server_combo.bind("<<ComboboxSelected>>", on_api_tcp_server_change)
        refresh_api_tcp_model_options(api_tcp_server_var.get())

        api_tcp_create_ui_var = tk.BooleanVar(value=self.api_tcp_create_ui_chats)
        api_tcp_folder_var = tk.StringVar(value=self.get_api_folder_name())

        def apply_api_folder_name():
            raw_value = (api_tcp_folder_var.get() or "").strip()
            if not raw_value:
                raw_value = "API Chats"
                api_tcp_folder_var.set(raw_value)
            if raw_value != self.api_tcp_folder_name:
                self.api_tcp_folder_name = raw_value
                self.reset_api_folder_cache()
                save_setting("api_tcp_folder_name", raw_value)

        def update_folder_entry_state():
            state = "normal" if api_tcp_create_ui_var.get() else "disabled"
            folder_entry.configure(state=state)

        def on_api_tcp_create_ui_toggle():
            new_value = api_tcp_create_ui_var.get()
            if new_value != self.api_tcp_create_ui_chats:
                self.api_tcp_create_ui_chats = new_value
                save_setting("api_tcp_create_ui_chats", "True" if new_value else "False")
            update_folder_entry_state()
            if new_value:
                apply_api_folder_name()

        ttk.Checkbutton(
            advanced_frame,
            text="Create API chats as UI chats",
            variable=api_tcp_create_ui_var,
            command=on_api_tcp_create_ui_toggle
        ).grid(row=advanced_row, column=0, columnspan=2, sticky="w", pady=(5, 10))
        advanced_row += 1

        ttk.Label(advanced_frame, text="Default Folder:").grid(row=advanced_row, column=0, sticky="w")
        folder_entry = ttk.Entry(advanced_frame, textvariable=api_tcp_folder_var)
        folder_entry.grid(row=advanced_row, column=1, sticky="ew")
        folder_entry.bind("<FocusOut>", lambda event: apply_api_folder_name())
        folder_entry.bind("<Return>", lambda event: (apply_api_folder_name(), "break"))
        advanced_row += 1
        update_folder_entry_state()

        ttk.Separator(advanced_frame, orient="horizontal").grid(row=advanced_row, column=0, columnspan=2, sticky="ew", pady=(5, 10))
        advanced_row += 1

        ttk.Label(advanced_frame, text="Ephemeral Chats:").grid(row=advanced_row, column=0, columnspan=2, sticky="w")
        advanced_row += 1

        self._ephemeral_stats_var = tk.StringVar(value="")
        stats_label = ttk.Label(advanced_frame, textvariable=self._ephemeral_stats_var)
        stats_label.grid(row=advanced_row, column=0, columnspan=2, sticky="w")
        advanced_row += 1
        self.refresh_ephemeral_stats_label()

        ttk.Button(advanced_frame, text="Clear Ephemeral Chats", command=self.clear_ephemeral_chats).grid(
            row=advanced_row, column=0, columnspan=2, sticky="w", pady=(5, 10)
        )
        advanced_row += 1

        ttk.Label(advanced_frame, text="Auto-clear after (minutes):").grid(row=advanced_row, column=0, sticky="w")
        ephemeral_ttl_var = tk.StringVar(value=str(self.api_tcp_ephemeral_ttl_minutes))

        def apply_ephemeral_ttl():
            raw_value = (ephemeral_ttl_var.get() or "").strip()
            new_value = self._coerce_positive_int(raw_value or self.api_tcp_ephemeral_ttl_minutes, default=self.api_tcp_ephemeral_ttl_minutes)
            new_value = min(1440, new_value)
            if str(new_value) != raw_value:
                ephemeral_ttl_var.set(str(new_value))
            if new_value != self.api_tcp_ephemeral_ttl_minutes:
                self.api_tcp_ephemeral_ttl_minutes = new_value
                save_setting("api_tcp_ephemeral_ttl_minutes", new_value)
                self.schedule_ephemeral_cleanup()

        ttl_spin = ttk.Spinbox(advanced_frame, from_=1, to=1440, textvariable=ephemeral_ttl_var, width=8, command=apply_ephemeral_ttl)
        ttl_spin.grid(row=advanced_row, column=1, sticky="w")
        ttl_spin.bind("<FocusOut>", lambda event: apply_ephemeral_ttl())
        ttl_spin.bind("<Return>", lambda event: (apply_ephemeral_ttl(), "break"))
        advanced_row += 1

        def on_settings_close():
            apply_api_folder_name()
            self._ephemeral_stats_var = None
            settings_win.destroy()

        settings_win.protocol("WM_DELETE_WINDOW", on_settings_close)
        apply_theme_styles()

    def export_chat(self, session_id=None, default_name=None):
        session_id = session_id or self.session_id
        if not session_id:
            messagebox.showinfo("Export Chat", "No chat selected to export.")
            return

        session_map, children_map = self._get_session_maps()
        record = session_map.get(session_id)
        if not record or record[8] != 'chat':
            messagebox.showerror("Export Error", "The selected item is not a chat.")
            return

        data = self._serialize_session_structure(session_id, session_map, children_map)
        if not data:
            messagebox.showerror("Export Error", "Unable to serialize the selected chat.")
            return

        session_name = default_name or record[1]
        initialfile = self._sanitize_filename(f"{session_name}_chat.json")
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.* ")],
            initialfile=initialfile
        )

        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4)
                messagebox.showinfo("Export Chat", "Chat exported successfully!")
            except Exception as e:
                messagebox.showerror("Export Error", f"Failed to export chat: {e}")

    def export_folder(self, folder_id, folder_name):
        session_map, children_map = self._get_session_maps()
        record = session_map.get(folder_id)
        if not record or record[8] != 'folder':
            messagebox.showerror("Export Error", "The selected item is not a folder.")
            return

        data = self._serialize_session_structure(folder_id, session_map, children_map)
        if not data:
            messagebox.showerror("Export Error", "Unable to serialize the selected folder.")
            return

        initialfile = self._sanitize_filename(f"{folder_name}_folder.json")
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.* ")],
            initialfile=initialfile
        )

        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4)
                messagebox.showinfo("Export Folder", "Folder exported successfully!")
            except Exception as e:
                messagebox.showerror("Export Error", f"Failed to export folder: {e}")

    def export_selected_item(self):
        selection = self.session_tree.selection()
        if not selection:
            messagebox.showinfo("Export", "Select a chat or folder to export.")
            return

        selected_item = selection[0]
        values = self.session_tree.item(selected_item, "values")
        if not values:
            messagebox.showinfo("Export", "No exportable item selected.")
            return

        session_id_str, item_type = values
        session_name = self.session_tree.item(selected_item, "text") or "Session"
        try:
            session_id = int(session_id_str)
        except (TypeError, ValueError):
            messagebox.showerror("Export Error", "Invalid selection.")
            return

        if item_type == 'folder':
            self.export_folder(session_id, session_name)
        else:
            self.export_chat(session_id=session_id, default_name=session_name)

    def import_chat_from_context(self):
        parent_id = self._determine_import_parent()
        self.import_chat(parent_id=parent_id, expected_type="chat")

    def import_folder_from_context(self):
        parent_id = self._determine_import_parent()
        self.import_chat(parent_id=parent_id, expected_type="folder")

    def import_chat(self, parent_id=None, expected_type="chat"):
        parent_id = self._coerce_parent_id(parent_id)
        if parent_id is None:
            parent_id = self._determine_import_parent()

        file_path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.* ")]
        )

        if not file_path:
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                imported_data = json.load(f)
        except json.JSONDecodeError:
            messagebox.showerror("Import Error", "Invalid JSON file.")
            return
        except Exception as e:
            messagebox.showerror("Import Error", f"Failed to read file: {e}")
            return

        import_type = self._detect_import_type(imported_data)
        if expected_type == "chat" and import_type == "folder":
            messagebox.showerror("Import Error", "Selected file contains a folder export. Use 'Import Folder...' instead.")
            return
        if expected_type == "folder" and import_type != "folder":
            messagebox.showerror("Import Error", "Selected file does not contain a folder export.")
            return

        default_name = os.path.splitext(os.path.basename(file_path))[0]
        override_name = None

        if import_type == "chat":
            existing_name = imported_data.get("name") if isinstance(imported_data, dict) else None
            prompt_name = existing_name or default_name or "Imported Chat"
            new_session_name = tk.simpledialog.askstring(
                "Import Chat",
                "Enter a name for the imported chat:",
                initialvalue=prompt_name
            )
            if not new_session_name:
                return
            override_name = new_session_name
        else:
            existing_name = imported_data.get("name") if isinstance(imported_data, dict) else None
            prompt_name = existing_name or default_name or "Imported Folder"
            new_folder_name = tk.simpledialog.askstring(
                "Import Folder",
                "Enter a name for the imported folder:",
                initialvalue=prompt_name
            )
            if not new_folder_name:
                return
            override_name = new_folder_name

        try:
            created_ids = self._import_session_data(
                imported_data,
                parent_id=parent_id,
                default_name=default_name,
                override_name=override_name
            )
        except ValueError as e:
            messagebox.showerror("Import Error", str(e))
            return
        except Exception as e:
            messagebox.showerror("Import Error", f"An unexpected error occurred: {e}")
            return

        if not created_ids:
            messagebox.showerror("Import Error", "Nothing was imported from the selected file.")
            return

        self.load_sessions()

        root_id = created_ids[0]
        new_item = self.find_tree_item_by_id(root_id)
        if new_item:
            self.session_tree.selection_set(new_item)
            self.session_tree.focus(new_item)
            self.session_tree.see(new_item)
            self.select_session(None)

        if import_type == "folder":
            messagebox.showinfo("Import Folder", "Folder imported successfully!")
        else:
            messagebox.showinfo("Import Chat", "Chat imported successfully!")

    def _coerce_parent_id(self, parent_id):
        if parent_id in (None, "", False):
            return None
        try:
            return int(parent_id)
        except (TypeError, ValueError):
            return None

    def _detect_import_type(self, data):
        if isinstance(data, dict) and data.get("type") == "folder":
            return "folder"
        return "chat"

    def _determine_import_parent(self):
        selection = self.session_tree.selection()
        if not selection:
            return None

        selected_item = selection[0]
        values = self.session_tree.item(selected_item, "values")
        if not values:
            return None

        session_id_str, item_type = values
        try:
            session_id = int(session_id_str)
        except (TypeError, ValueError):
            return None

        if item_type == 'folder':
            return session_id

        record = self._get_session_record(session_id)
        if record:
            parent_id = record[7]
            return int(parent_id) if parent_id is not None else None
        return None

    def _sanitize_filename(self, name):
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "")
        safe = safe.strip("._")
        return safe or "session"

    def _get_session_maps(self):
        session_map = {}
        children_map = {}
        for record in get_sessions():
            session_id = record[0]
            try:
                session_id = int(session_id)
            except (TypeError, ValueError):
                pass

            session_map[session_id] = record

            parent = record[7]
            if isinstance(parent, str):
                parent_stripped = parent.strip()
                if parent_stripped.lower() in ("", "none", "null", "nil"):
                    parent = None
                else:
                    try:
                        parent = int(parent_stripped)
                    except ValueError:
                        parent = None
            elif parent is not None:
                try:
                    parent = int(parent)
                except (TypeError, ValueError):
                    parent = None

            children_map.setdefault(parent, []).append(record)
        return session_map, children_map

    def _collect_descendant_ids(self, session_id, children_map):
        try:
            root_id = int(session_id)
        except (TypeError, ValueError):
            root_id = session_id

        descendants = []
        visited = set()
        stack = [root_id]
        while stack:
            current = stack.pop()
            for child_record in children_map.get(current, []):
                raw_child_id = child_record[0]
                try:
                    child_id = int(raw_child_id)
                except (TypeError, ValueError):
                    child_id = raw_child_id
                if child_id in visited:
                    continue
                visited.add(child_id)
                descendants.append(child_id)
                stack.append(child_id)
        return descendants

    def _serialize_session_structure(self, session_id, session_map, children_map):
        lookup_id = session_id
        if isinstance(lookup_id, str):
            try:
                lookup_id = int(lookup_id.strip())
            except ValueError:
                pass
        record = session_map.get(lookup_id)
        if not record:
            return None

        raw_id = record[0]
        try:
            record_id = int(raw_id)
        except (TypeError, ValueError):
            record_id = raw_id

        _id, name, model, server_name, last_model_used, system_prompt, sp_id, parent_id, item_type = record
        if item_type == 'folder':
            children_serialized = []
            for child_record in children_map.get(record_id, []):
                child_data = self._serialize_session_structure(child_record[0], session_map, children_map)
                if child_data:
                    children_serialized.append(child_data)
            return {
                "type": "folder",
                "name": name,
                "children": children_serialized
            }

        messages_payload = []
        for role, content in get_messages(record_id):
            messages_payload.append({"role": role, "content": content})

        return {
            "type": "chat",
            "name": name,
            "model": model,
            "server": server_name,
            "system_prompt": system_prompt,
            "system_prompt_id": sp_id,
            "last_model_used": (last_model_used or model),
            "messages": messages_payload
        }

    def _import_session_data(self, data, parent_id=None, default_name=None, override_name=None):
        created_ids = []
        if isinstance(data, dict) and data.get("type") == "folder":
            folder_name = override_name or data.get("name") or default_name or "Imported Folder"
            folder_id = create_session(
                folder_name,
                model='gpt-3.5-turbo',
                type='folder',
                parent_id=parent_id,
                last_model_used='gpt-3.5-turbo'
            )
            created_ids.append(folder_id)
            for child in data.get("children", []):
                created_ids.extend(self._import_session_data(child, parent_id=folder_id))
            return created_ids

        if isinstance(data, dict):
            messages_data = data.get("messages", [])
            model = data.get("model", "gpt-3.5-turbo")
            last_model = data.get("last_model_used", model)
            system_prompt = data.get("system_prompt", "")
            system_prompt_id = data.get("system_prompt_id")
            server = data.get("server") or self.server_var.get()
            session_name = override_name or data.get("name") or default_name or "Imported Chat"
        elif isinstance(data, list):
            messages_data = data
            model = "gpt-3.5-turbo"
            last_model = model
            system_prompt = ""
            system_prompt_id = None
            server = self.server_var.get()
            session_name = override_name or default_name or "Imported Chat"
        else:
            raise ValueError("Unsupported chat format in import data.")

        processed_messages = []
        for msg in messages_data:
            if isinstance(msg, dict):
                role = msg.get("role")
                content = msg.get("content")
            elif isinstance(msg, (list, tuple)) and len(msg) >= 2:
                role, content = msg[0], msg[1]
            else:
                continue
            if not role or content is None:
                continue
            processed_messages.append((role, content))

        session_id = create_session(
            session_name,
            model,
            system_prompt,
            parent_id=parent_id,
            system_prompt_id=system_prompt_id,
            last_model_used=last_model,
            server_name=server
        )
        for role, content in processed_messages:
            save_message(session_id, role, content)
        created_ids.append(session_id)
        return created_ids

    def export_system_prompts(self):
        prompts = get_system_prompts()
        if not prompts:
            messagebox.showinfo("Export System Prompts", "No system prompts to export.")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.* ")],
            initialfile="system_prompts.json",
        )

        if file_path:
            try:
                data = [{"title": title, "prompt": prompt} for _, title, prompt in prompts]
                with open(file_path, "w") as f:
                    json.dump(data, f, indent=4)
                messagebox.showinfo("Export System Prompts", "System prompts exported successfully!")
            except Exception as e:
                messagebox.showerror("Export Error", f"Failed to export system prompts: {e}")

    def import_system_prompts(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.* ")]
        )

        if not file_path:
            return

        try:
            with open(file_path, "r") as f:
                data = json.load(f)

            if isinstance(data, dict) and "prompts" in data:
                prompts = data["prompts"]
            else:
                prompts = data

            if not isinstance(prompts, list):
                raise ValueError("Invalid JSON format for system prompts")

            count = 0
            for item in prompts:
                if isinstance(item, dict):
                    title = item.get("title")
                    prompt = item.get("prompt")
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    title, prompt = item[0], item[1]
                else:
                    continue
                if title and prompt:
                    save_system_prompt(title, prompt)
                    count += 1

            self.load_system_prompts_to_dropdown()
            messagebox.showinfo("Import System Prompts", f"Imported {count} prompts!")
        except json.JSONDecodeError:
            messagebox.showerror("Import Error", "Invalid JSON file.")
        except Exception as e:
            messagebox.showerror("Import Error", f"Failed to import system prompts: {e}")

    def new_folder(self, parent_id=None):
        name = self._prompt_at_cursor("New Folder", "Enter folder name:")
        if name:
            db_parent_id = int(parent_id) if parent_id is not None else None
            session_id = create_session(name, model='gpt-3.5-turbo', type='folder', parent_id=db_parent_id, last_model_used='gpt-3.5-turbo')
            parent_node = self.find_tree_item_by_id(parent_id) if parent_id is not None else ""
            if parent_node is None:
                parent_node = ""
            self.session_tree.insert(parent_node, "end", text=name, values=(str(session_id), 'folder'), image=self.folder_icon)

    def load_sessions(self, open_folders=None, set_selection=True):
        if open_folders is None:
            open_folders = set()

        for i in self.session_tree.get_children():
            self.session_tree.delete(i)
        
        sessions = get_sessions()
        session_map = {s[0]: s for s in sessions}

        def add_to_tree(parent_id, parent_node=""):
            for _id, name, model, server_name, last_model_used, system_prompt, sp_id, s_parent_id, type in sessions:
                if s_parent_id == parent_id:
                    icon = self.chat_icon if type == 'chat' else self.folder_icon
                    node = self.session_tree.insert(parent_node, "end", text=name, values=(str(_id), type), image=icon)
                    if type == 'folder':
                        add_to_tree(_id, node)

        add_to_tree(None)

        if sessions and set_selection:
            first_item = self.session_tree.get_children()[0]
            self.session_tree.selection_set(first_item)
            self.session_tree.focus(first_item)

    def select_session(self, event):
        selection = self.session_tree.selection()
        if not selection:
            return
        selected_item = selection[0]
        _id, type = self.session_tree.item(selected_item, "values")
        _id = int(_id)

        
        if type == 'folder':
            self.session_id = None
            self.session_name = None
            self.last_model_used = None
            self.title(f"{APP_NAME} Client")
            self.chat_history.configure(state="normal")
            self.chat_history.delete("1.0", tk.END)
            self.chat_history.configure(state="normal")
            self.chat_files = []
            self.update_files_listbox()
            self.update_input_widgets_state()
            self.refresh_last_model_label()
            return

        for sid, name, model, server_name, last_model_used, system_prompt, sp_id, parent_id, stype in get_sessions():
            if sid == _id:
                self.session_name = name
                self.session_id = _id
                self.title(f"{APP_NAME} - {self.session_name}")
                self.last_model_used = last_model_used or model

                stored_server = server_name
                desired_server = stored_server or self.server_var.get() or self.server_manager.get_active_server_name()
                server_config = self.server_manager.get_server(desired_server) if desired_server else None

                if stored_server and not server_config:
                    messagebox.showerror(
                        "Server Missing",
                        f"The server '{stored_server}' configured for this chat is not available.",
                        parent=self
                    )
                    fallback_name = self.server_manager.get_active_server_name()
                    if fallback_name and fallback_name != stored_server:
                        desired_server = fallback_name
                        server_config = self.server_manager.get_server(fallback_name)
                    else:
                        desired_server = None

                if not server_config:
                    available_names = self.server_manager.list_server_names()
                    if not available_names:
                        messagebox.showerror(
                            "No Servers",
                            "No server configurations are available. Please add a server before continuing.",
                            parent=self
                        )
                        self.server_var.set("")
                        self.current_server_config = None
                        set_current_server_config(None)
                        self.model_dropdown['values'] = []
                        effective_model = None
                    else:
                        # Fall back to the first available server
                        desired_server = available_names[0]
                        server_config = self.server_manager.get_server(desired_server)
                        self._pending_preferred_model = model
                        self._suppress_server_status_message = True
                        self.server_var.set(desired_server)
                        self.on_server_selected()
                        effective_model = self.model_var.get()
                else:
                    if (self.server_var.get() != desired_server) or (self.current_server_config != server_config):
                        self._pending_preferred_model = model
                        self._suppress_server_status_message = True
                        self.server_var.set(desired_server)
                        self.on_server_selected()
                    else:
                        self.refresh_model_dropdown(initial=False, preferred_model=model)
                        if desired_server:
                            update_session_server(self.session_id, desired_server)
                    effective_model = self.model_var.get()

                if server_config:
                    available_model = effective_model
                    if model and available_model != model:
                        messagebox.showerror(
                            "Model Missing",
                            f"The model '{model}' is not available on server '{desired_server}'.\n"
                            f"Using '{available_model}' instead.",
                            parent=self
                        )
                        update_session_model(self.session_id, available_model)
                    elif not model and available_model:
                        update_session_model(self.session_id, available_model)

                # Load system prompt
                self.system_prompt_text.delete("1.0", tk.END)
                if system_prompt:
                    self.system_prompt_text.insert("1.0", system_prompt)
                self.current_system_prompt_id = sp_id
                self.system_prompt_var.set("New...")
                for pid, title, _ in self.system_prompts:
                    if pid == sp_id:
                        self.system_prompt_var.set(title)
                        break

                if rag_functions:
                    self.chat_files = rag_functions['get_files_for_chat'](self.session_id)
                else:
                    self.chat_files = []
                self.update_files_listbox()
                self.load_chat_history()
                self.message_history = get_input_history(self.session_id)
                self.history_index = len(self.message_history)
                self.current_input_buffer = ""
                self.update_input_widgets_state()
                self.refresh_last_model_label()
                break
        else:
            self.title(f"{APP_NAME}")
            self.last_model_used = None
            self.update_input_widgets_state()
            self.refresh_last_model_label()
            return

    def get_session_id_by_name(self, name):
        for _id, s_name, model, server_name, last_model_used, system_prompt, sp_id, parent_id, type in get_sessions():
            if s_name == name:
                return _id
        return None

    def find_tree_item_by_id(self, target_id):
        if target_id is None:
            return None
        target_id_str = str(target_id)
        def search_children(parent_item):
            for item in self.session_tree.get_children(parent_item):
                item_values = self.session_tree.item(item, "values")
                if item_values and item_values[0] == target_id_str:
                    return item
                found = search_children(item)
                if found:
                    return found
            return None
        return search_children("")

    def update_input_widgets_state(self):
        if self.session_id is None:
            self.input_box.configure(state="disabled")
            self.send_button.configure(state="disabled")
            self.files_button.configure(state="disabled")
            self.status_bar.config(text="Please select or create a chat session.")
        else:
            self.input_box.configure(state="normal")
            self.send_button.configure(state="normal")
            self.files_button.configure(state="normal" if self.rag_enabled else "disabled")
            self.status_bar.config(text="")

    def new_session(self, parent_id=None):
        name = f"Session {len(get_sessions()) + 1}"
        default_model = None
        if self.current_server_config:
            default_model = self.current_server_config.get("default_model")
        available_models = get_available_models(self.current_server_config)
        if not default_model or default_model not in available_models:
            default_model = available_models[0] if available_models else "gpt-3.5-turbo"
        
        if parent_id is None:
            selection = self.session_tree.selection()
            if selection:
                selected_item = selection[0]
                item_type = self.session_tree.item(selected_item, "values")[1]
                if item_type == 'folder':
                    parent_id = self.session_tree.item(selected_item, "values")[0]

        db_parent_id = int(parent_id) if parent_id is not None else None
        session_id = create_session(
            name,
            default_model,
            parent_id=db_parent_id,
            system_prompt_id=getattr(self, "current_system_prompt_id", None),
            last_model_used=default_model,
            server_name=self.server_var.get()
        )
        
        parent_node = self.find_tree_item_by_id(parent_id) if parent_id is not None else ""
        if parent_node is None:
            parent_node = ""
        new_item = self.session_tree.insert(parent_node, "end", text=name, values=(str(session_id), 'chat'), image=self.chat_icon)
        self.session_tree.selection_set(new_item)
        self.session_tree.focus(new_item)
        self.select_session(None) # Manually trigger selection logic

    def show_status_message(self, message, duration=3000):
        self.status_bar.config(text=message)
        self.after(duration, lambda: self.status_bar.config(text=""))


    def copy_message_from_link(self, event):
        try:
            index = self.chat_history.index(f"@{event.x},{event.y}")
            tags_at_index = self.chat_history.tag_names(index)
            
            # Find the unique copy link tag
            copy_link_tag = None
            for tag in tags_at_index:
                if tag.startswith("copy_link_for_"):
                    copy_link_tag = tag
                    break
            
            if copy_link_tag:
                # Extract the message body tag from the copy link tag
                message_body_tag = copy_link_tag.replace("copy_link_for_", "")
                
                message_range = self.chat_history.tag_ranges(message_body_tag)
                if message_range:
                    message_start_index, message_end_index = message_range
                    message_text = self.chat_history.get(message_start_index, message_end_index)
                    
                    self.clipboard_clear()
                    self.clipboard_append(message_text.strip())
                    self.show_status_message("Copied to clipboard!")
        except tk.TclError:
            # This can happen if the click is not on a tagged range
            pass
        except Exception as e:
            print(f"Error copying message: {e}")

    def show_chat_context_menu(self, event):
        self.close_all_menus()
        if self.chat_history.tag_ranges("sel"):
            self.selection_context_menu.post(event.x_root, event.y_root)
        else:
            self.chat_history_menu.post(event.x_root, event.y_root)

    def process_selection(self, action):
        try:
            selected_text = self.chat_history.get(tk.SEL_FIRST, tk.SEL_LAST)
            if not selected_text:
                return

            prompt_map = {
                "summarize": "Summarize the following text",
                "tldr": "Provide a TL;DR version of the following text",
                "explain_simple": "Explain the following text in simpler terms",
                "explain_more": "Tell me more about the following text",
                "explain_detail": "Add more detail and examples to the following text",
                "rewrite_rephrase": "Rephrase the following text",
                "rewrite_formal": "Make the following text more formal",
                "rewrite_informal": "Make the following text more informal",
                "rewrite_professional": "Make the following text more professional",
                "rewrite_improve": "Improve the grammar and style of the following text",
                "translate_english": "Translate the following text to English",
                "translate_detect": "Detect the language of the following text and translate it to English",
                "analyze_sentiment": "Analyze the sentiment and tone of the following text",
                "analyze_bias": "Identify any assumptions or bias in the following text",
                "analyze_topic": "Classify the topic of the following text",
                "ask_generate": "Generate questions from this text",
                "ask_what_questions": "What questions can I ask about this?",
                "extract_key_points": "Highlight the key points in the following text",
                "extract_entities": "Extract named entities (people, places, dates, etc.) from the following text",
                "extract_action_items": "Pull out any action items from the following text",
                "expand_continue": "Continue writing from here",
                "expand_follow_up": "Generate a follow-up paragraph, story, or argument based on the following text",
                "define_terms": "Define the following term(s)",
                "define_context": "Provide background or context for the following text",
                "respond_reply": "Write a reply or response to the following text",
            }

            if action == "respond_discuss":
                self.start_discussion_from_selection()
                return

            if action in prompt_map:
                prompt_text = prompt_map[action]
                full_prompt = f"{prompt_text}:\n\n---\n\n{selected_text}"
                self.send_prompt_as_user(full_prompt)
            
        except tk.TclError:
            # This can happen if there is no selection
            pass
        except Exception as e:
            messagebox.showerror("Error", f"An unexpected error occurred: {e}")

    def send_prompt_as_user(self, prompt_content):
        if not self.session_id:
            messagebox.showinfo("Action", "Please select a session first.")
            return

        active_session_id = self.session_id
        save_message(self.session_id, "user", prompt_content)
        save_input_history(self.session_id, prompt_content)
        self.message_history = get_input_history(self.session_id)
        self.history_index = len(self.message_history)
        
        messages = get_messages(self.session_id)
        message_blocks = [{"role": role, "content": content} for role, content in messages]
        
        system_prompt = self.system_prompt_text.get("1.0", tk.END).strip()
        if system_prompt:
            message_blocks.insert(0, {"role": "system", "content": system_prompt})
        update_session_system_prompt(self.session_id, system_prompt)
        update_session_system_prompt_id(self.session_id, getattr(self, "current_system_prompt_id", None))

        # RAG workflow: If chat has associated files, retrieve context from ChromaDB
        context_block = None
        if rag_functions and self.chat_files:
            if not rag_functions['is_rag_loaded']():
                self.show_status_message("RAG processing initializing...")
                print("RAG processing initializing...")
            try:
                # Embed query and retrieve top-K relevant chunks
                top_k = 5
                rag_results = rag_functions['query_by_chat_id'](self.session_id, prompt_content, n_results=top_k)
                if rag_results:
                    context_texts = [r['text'] for r in rag_results]
                    context_block = '\n---\n'.join(context_texts)
                    # Prepend context to user message
                    content_with_context = f"Context:\n{context_block}\n\nUser Query: {prompt_content}"
                    # Replace user message in message_blocks
                    for msg in message_blocks:
                        if msg['role'] == 'user' and msg['content'] == prompt_content:
                            msg['content'] = content_with_context
                            break
            except Exception as e:
                self.show_status_message(f"RAG context retrieval failed: {e}")

        self.load_chat_history()
        self.update_idletasks()

        try:
            send_to_api(
                self.session_name,
                message_blocks,
                self.model_var.get(),
                active_session_id,
                server_config=self.current_server_config,
                widget=self.chat_history
            )
        except Exception as e:
            messagebox.showerror("API Error", str(e))

        self.load_chat_history()

        item_to_select = self.find_tree_item_by_id(active_session_id)
        if item_to_select:
            self.session_tree.selection_set(item_to_select)
            self.session_tree.focus(item_to_select)

    def start_discussion_from_selection(self):
        try:
            selected_text = self.chat_history.get(tk.SEL_FIRST, tk.SEL_LAST)
            if not selected_text:
                return

            # Summarize the selected text to create a title for the new session
            prompt = f"Summarize the following text in 5 words or less to use as a title for a new chat session:\n\n{selected_text}"
            messages = [{"role": "user", "content": prompt}]
            
            # Call send_to_api without a widget to get the response directly
            summary_model = self.model_var.get()
            new_session_name = send_to_api(
                "New Discussion",
                messages,
                summary_model,
                self.session_id,
                server_config=self.current_server_config,
                widget=None,
                save_message_to_db=False
            ).strip().strip('"') # Strip quotes from the response

            if not new_session_name:
                new_session_name = "New Discussion"

            # Create a new session with the generated title
            new_session_id = create_session(
                new_session_name,
                self.model_var.get(),
                self.system_prompt_text.get("1.0", tk.END).strip(),
                system_prompt_id=getattr(self, "current_system_prompt_id", None),
                last_model_used=self.model_var.get(),
                server_name=self.server_var.get()
            )
            save_message(new_session_id, "user", f"Let's discuss the following:\n\n{selected_text}")
            self.load_sessions()
            
            # Select the new session
            item_to_select = self.find_tree_item_by_id(new_session_id)
            if item_to_select:
                self.session_tree.selection_set(item_to_select)
                self.session_tree.focus(item_to_select)

        except tk.TclError:
            # This can happen if there is no selection
            pass
        except Exception as e:
            messagebox.showerror("Error", f"An unexpected error occurred: {e}")

    def copy_chat_selection(self):
        try:
            selected_text = self.chat_history.get(tk.SEL_FIRST, tk.SEL_LAST)
            self.clipboard_clear()
            self.clipboard_append(selected_text)
            self.show_status_message("Copied to clipboard!")
        except tk.TclError:
            # This can happen if there is no selection
            pass

    def load_chat_history(self):
        self.chat_history.configure(state="normal")
        self.chat_history.delete("1.0", tk.END)
        # Insert anchor at the start of chat
        self.chat_history.insert(tk.END, "", "start_anchor")
        messages = get_messages(self.session_id)
        for i, (role, content) in enumerate(messages):
            anchor_name = f"msg_start_{i}"
            # Insert a newline with the anchor tag so it's a valid index
            self.chat_history.insert(tk.END, "\n", anchor_name)
            if role == 'user':
                self.chat_history.insert(tk.END, f"User:\n", ("user_tag", "bold"))
                render_markdown_in_widget(self.chat_history, content)
                self.chat_history.insert(tk.END, "\n\n")
            elif role == 'assistant':
                self.chat_history.insert(tk.END, f"Assistant:\n", ("assistant_tag", "bold"))
                
                message_start_index = self.chat_history.index(tk.INSERT)
                render_markdown_in_widget(self.chat_history, content)
                message_end_index = self.chat_history.index(tk.INSERT)

                # Unique tags for each message body and its copy link
                message_body_tag = f"assistant_message_body_{i}"
                copy_link_tag = f"copy_link_for_{message_body_tag}"

                self.chat_history.tag_add(message_body_tag, message_start_index, message_end_index)
                
                self.chat_history.insert(tk.END, "Copy", ("copy_link", copy_link_tag))
                # Insert 'Start' link styled as hyperlink
                self.chat_history.tag_config(f"start_link_{i}", foreground="blue", underline=True)
                self.chat_history.insert(tk.END, " | Start", (f"start_link_{i}",))
                self.chat_history.tag_bind(f"start_link_{i}", "<Button-1>", lambda e, idx=i: self.chat_history.see(f"msg_start_{idx}.first"))
                self.chat_history.tag_bind(f"start_link_{i}", "<Enter>", lambda e: self.chat_history.config(cursor="hand2"))
                self.chat_history.tag_bind(f"start_link_{i}", "<Leave>", lambda e: self.chat_history.config(cursor=""))
                self.chat_history.insert(tk.END, "\n\n")

        # Add a clickable 'start' link at the top
        self.chat_history.insert("1.0", "start", ("copy_link", "start_link"))
        self.chat_history.tag_bind("start_link", "<Button-1>", lambda e: self.chat_history.see("start_anchor.first"))
        self.chat_history.see(tk.END)
        self.chat_history.configure(state="disabled")

    def _collect_conversation(self, session_id):
        messages = get_messages(session_id)
        if len(messages) < 2:
            return None, messages
        conversation = "\n".join(f"{role.title()}: {content}" for role, content in messages)
        return conversation, messages

    def _generate_chat_title(self, session_id, conversation, current_name, model):
        prompt = (
            f"The current chat session name is '{current_name}'. Summarize the following conversation in 5 words or less. "
            "This summary will be used as the new session name. Only change the name if a significant topic shift occurs. "
            "Do not use quotes in the summary.\n\nConversation:\n"
            f"{conversation}"
        )
        messages_for_summary = [
            {"role": "system", "content": "You are a helpful assistant that summarizes chat sessions for use as a new session name."},
            {"role": "user", "content": prompt}
        ]
        response = send_to_api(
            current_name,
            messages_for_summary,
            model,
            session_id,
            server_config=self.current_server_config,
            widget=None,
            save_message_to_db=False
        )
        return response.strip().strip('"')

    def _get_session_record(self, session_id):
        for record in get_sessions():
            if record[0] == session_id:
                return record
        return None

    def _confirm_at_cursor(self, title, message):
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.configure(padx=10, pady=10)

        x = self.winfo_pointerx()
        y = self.winfo_pointery()
        dialog.geometry(f"+{x}+{y}")

        ttk.Label(dialog, text=message, wraplength=320, justify=tk.LEFT).pack(pady=(0, 10))

        result = {"value": False}

        def on_yes():
            result["value"] = True
            dialog.destroy()

        def on_no():
            dialog.destroy()

        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X)

        yes_btn = ttk.Button(button_frame, text="Yes", command=on_yes)
        yes_btn.pack(side=tk.LEFT, padx=(0, 5))

        no_btn = ttk.Button(button_frame, text="No", command=on_no)
        no_btn.pack(side=tk.LEFT)

        dialog.bind("<Return>", lambda e: on_yes())
        dialog.bind("<Escape>", lambda e: on_no())
        yes_btn.focus_set()
        self.wait_window(dialog)
        return result["value"]

    def _prompt_at_cursor(self, title, message, initial=""):
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.configure(padx=10, pady=10)

        x = self.winfo_pointerx()
        y = self.winfo_pointery()
        dialog.geometry(f"+{x}+{y}")

        ttk.Label(dialog, text=message, justify=tk.LEFT).pack(pady=(0, 8))

        entry = ttk.Entry(dialog, width=30)
        entry.insert(0, initial or "")
        entry.pack(fill=tk.X)

        result = {"value": None}

        def on_ok():
            result["value"] = entry.get().strip()
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=(8, 0))

        ttk.Button(button_frame, text="OK", command=on_ok).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Cancel", command=on_cancel).pack(side=tk.LEFT)

        dialog.bind("<Return>", lambda e: on_ok())
        dialog.bind("<Escape>", lambda e: on_cancel())
        entry.focus_set()
        entry.select_range(0, tk.END)
        self.wait_window(dialog)
        return result["value"]

    def refresh_last_model_label(self):
        if hasattr(self, "last_model_label"):
            last = self.last_model_used or "Unknown"
            current = self.model_var.get() if hasattr(self, "model_var") else ""
            current = current or "Unknown"
            self.last_model_label.configure(text=f"Last model used: {last}, Current model: {current}")

    def summarize_and_rename_session(self, force=False):
        if not self.session_id or not self.session_name:
            return

        if not force and not self.auto_summarize_enabled():
            return

        conversation, messages = self._collect_conversation(self.session_id)
        if not conversation:
            if force:
                self.show_status_message("Not enough conversation to summarize", duration=3000)
            return

        try:
            self.show_status_message("Updating chat summary...")
            summary_model = self.model_var.get()
            new_name = self._generate_chat_title(self.session_id, conversation, self.session_name, summary_model)

            def ensure_api_prefix(candidate, original):
                if not original:
                    return candidate
                if not candidate:
                    return candidate
                prefixes = ["API:", "API Chat:"]
                if any(original.startswith(prefix) for prefix in prefixes):
                    base = candidate.lstrip()
                    if not any(base.startswith(prefix) for prefix in prefixes):
                        return f"API: {base}" if base else "API:"
                return candidate

            new_name = ensure_api_prefix(new_name, self.session_name)

            if new_name and new_name != self.session_name and len(new_name.split()) <= 7:
                item_to_select = self.find_tree_item_by_id(self.session_id)
                if not item_to_select:
                    return 

                update_session_name(self.session_id, new_name)
                self.session_name = new_name
                
                # Update the name in the listbox directly
                self.session_tree.item(item_to_select, text=new_name)
                self.title(f"{APP_NAME} - {self.session_name}")

                self.show_status_message("Chat summary updated")
            else:
                self.show_status_message("Chat summary unchanged", duration=2000)


        except Exception as e:
            print(f"Error summarizing session: {e}")
            self.show_status_message("Chat summary update failed", duration=4000)

    def auto_rename_selected_session(self):
        self.close_all_menus()
        selection = self.session_tree.selection()
        if not selection:
            return
        selected_item = selection[0]
        session_id_str, item_type = self.session_tree.item(selected_item, "values")
        if item_type == 'folder':
            self.show_status_message("Select a chat to rename", duration=3000)
            return
        session_id = int(session_id_str)
        self.session_tree.selection_set(selected_item)
        self.session_tree.focus(selected_item)
        self.select_session(None)
        if self.session_id != session_id:
            return
        self.summarize_and_rename_session(force=True)

    def summarize_and_start_new_chat(self):
        self.close_all_menus()
        selection = self.session_tree.selection()
        if not selection:
            return
        selected_item = selection[0]
        session_id_str, item_type = self.session_tree.item(selected_item, "values")
        if item_type == 'folder':
            self.show_status_message("Select a chat to summarize", duration=3000)
            return
        session_id = int(session_id_str)
        self.session_tree.selection_set(selected_item)
        self.session_tree.focus(selected_item)
        self.select_session(None)
        if self.session_id != session_id:
            session_id = self.session_id

        conversation, messages = self._collect_conversation(session_id)
        if not conversation:
            self.show_status_message("Not enough conversation to summarize", duration=3000)
            return

        try:
            self.show_status_message("Creating summary chat...")
            summary_prompt = (
                "Create a concise summary of the following conversation in one to two paragraphs. "
                "Capture the key ideas, decisions, and any suggested next steps. Use complete sentences."
            )
            summary_messages = [
                {"role": "system", "content": "You summarize chats into concise, well-structured prose for quick review."},
                {"role": "user", "content": f"{summary_prompt}\n\nConversation:\n{conversation}"}
            ]
            summary_model = self.model_var.get()
            summary_text = send_to_api(
                f"{self.session_name} Summary",
                summary_messages,
                summary_model,
                session_id,
                server_config=self.current_server_config,
                widget=None,
                save_message_to_db=False
            ).strip()
        except Exception as e:
            self.show_status_message(f"Summary generation failed: {e}", duration=4000)
            return

        if not summary_text:
            self.show_status_message("Summary generation returned empty response", duration=4000)
            return

        try:
            new_title = self._generate_chat_title(session_id, conversation, self.session_name, summary_model)
        except Exception as e:
            print(f"Error generating summary chat title: {e}")
            new_title = None

        if not new_title:
            new_title = f"{self.session_name} Summary"

        prefixes = ["API:", "API Chat:"]
        if any((self.session_name or "").startswith(prefix) for prefix in prefixes):
            base = new_title.lstrip()
            if not any(base.startswith(prefix) for prefix in prefixes):
                new_title = f"API: {base}" if base else "API:" 

        record = self._get_session_record(session_id)
        parent_id = None
        system_prompt = ""
        sp_id = None
        model = summary_model
        last_model_used = summary_model
        if record:
            _, _, model, server_name, _, system_prompt, sp_id, parent_id, _ = record
        else:
            system_prompt = self.system_prompt_text.get("1.0", tk.END).strip()
            server_name = self.server_var.get()

        new_session_id = create_session(
            new_title,
            model,
            system_prompt,
            parent_id=parent_id,
            system_prompt_id=sp_id,
            last_model_used=last_model_used,
            server_name=server_name
        )
        save_message(new_session_id, "assistant", summary_text.strip())
        self.load_sessions()

        new_item = self.find_tree_item_by_id(new_session_id)
        if new_item:
            self.session_tree.selection_set(new_item)
            self.session_tree.focus(new_item)
            self.session_tree.see(new_item)
            self.session_tree.event_generate('<<TreeviewSelect>>')

        self.show_status_message(f"Created summary chat '{new_title}'", duration=4000)

    def copy_selected_session(self):
        self.close_all_menus()
        selection = self.session_tree.selection()
        if not selection:
            return
        selected_item = selection[0]
        session_id_str, item_type = self.session_tree.item(selected_item, "values")
        if item_type == 'folder':
            self.show_status_message("Select a chat to copy", duration=3000)
            return

        session_id = int(session_id_str)
        record = self._get_session_record(session_id)
        if not record:
            self.show_status_message("Unable to load chat for copying", duration=3000)
            return

        _, name, model, server_name, last_model_used, system_prompt, system_prompt_id, parent_id, _ = record

        conversation_messages = get_messages(session_id)
        new_name = f"{name} (Copy)"

        new_session_id = create_session(
            new_name,
            model,
            system_prompt,
            parent_id=parent_id,
            system_prompt_id=system_prompt_id,
            last_model_used=last_model_used or model,
            server_name=server_name
        )

        for role, content in conversation_messages:
            save_message(new_session_id, role, content)

        self.load_sessions()
        new_item = self.find_tree_item_by_id(new_session_id)
        if new_item:
            self.session_tree.selection_set(new_item)
            self.session_tree.focus(new_item)
            self.session_tree.see(new_item)
            self.session_tree.event_generate('<<TreeviewSelect>>')

        self.show_status_message(f"Copied chat to '{new_name}'", duration=4000)

    def manage_files_for_selection(self):
        self.close_all_menus()
        selection = self.session_tree.selection()
        if not selection:
            return
        selected_item = selection[0]
        values = self.session_tree.item(selected_item, "values")
        if not values or values[1] != 'chat':
            return

        session_id = int(values[0])
        if self.session_id != session_id:
            self.session_tree.selection_set(selected_item)
            self.session_tree.focus(selected_item)
            self.session_tree.event_generate('<<TreeviewSelect>>')

        position = (self.winfo_pointerx(), self.winfo_pointery())
        self.open_files_dialog(position=position)

    def close_files_dialog(self):
        if hasattr(self, 'files_window') and self.files_window.winfo_exists():
            self.files_window.grab_release()
            self.files_window.destroy()

    def open_files_dialog(self, position=None):
        width, height = 400, 300

        def apply_geometry(pos):
            if pos:
                x = max(int(pos[0] - width / 2), 0)
                y = max(int(pos[1] - height / 2), 0)
                self.files_window.geometry(f"{width}x{height}+{x}+{y}")
            else:
                self.files_window.geometry(f"{width}x{height}")

        if hasattr(self, 'files_window') and self.files_window.winfo_exists():
            if position:
                apply_geometry(position)
            self.files_window.lift()
            return

        self.files_window = tk.Toplevel(self)
        self.files_window.title("Attached Files")
        apply_geometry(position)

        self.files_window.transient(self)
        self.files_window.grab_set()
        self.files_window.protocol("WM_DELETE_WINDOW", self.close_files_dialog)
        self.files_window.bind("<Escape>", lambda event: (self.close_files_dialog(), "break"))

        frame = ttk.Frame(self.files_window, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        self.files_listbox = tk.Listbox(frame)
        self.files_listbox.pack(fill=tk.BOTH, expand=True, side=tk.LEFT, padx=(0, 10))

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.files_listbox.yview)
        scrollbar.pack(fill=tk.Y, side=tk.RIGHT)
        self.files_listbox.config(yscrollcommand=scrollbar.set)

        button_frame = ttk.Frame(self.files_window, padding=(10,0,10,10))
        button_frame.pack(fill=tk.X)

        add_button = ttk.Button(button_frame, text="Add Files", command=self.add_files_to_list)
        add_button.pack(side=tk.LEFT, padx=(0, 5))

        add_url_button = ttk.Button(button_frame, text="Add URL", command=self.add_url_to_list)
        add_url_button.pack(side=tk.LEFT, padx=(0, 5))
        if not rag_functions:
            add_url_button.configure(state="disabled")

        remove_button = ttk.Button(button_frame, text="Remove", command=self.remove_selected_file)
        remove_button.pack(side=tk.LEFT)

        self.files_listbox_menu = tk.Menu(self.files_listbox, tearoff=0)
        self.files_listbox_menu.add_command(label="Remove", command=self.remove_selected_file)
        self.files_listbox.bind("<Button-3>", self.show_files_listbox_menu)
        if self.files_listbox_menu not in self.context_menus:
            self.context_menus.append(self.files_listbox_menu)

        self.update_files_listbox()
        self.create_files_listbox_tooltip()

    def add_files_to_list(self):
        files = filedialog.askopenfilenames(parent=self.files_window)
        if files:
            for file_path in files:
                if file_path not in self.chat_files:
                    self.chat_files.append(file_path)
                    self.process_new_chat_file(file_path)
            self.update_files_listbox()

    def _normalize_url(self, url):
        if not url:
            return None
        url = url.strip()
        if not url:
            return None
        if not re.match(r'^https?://', url, re.IGNORECASE):
            url = f"https://{url}"
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return None
        return url

    def _format_url_display(self, url, suffix=True):
        try:
            parsed = urlparse(url)
            if not parsed.netloc:
                raise ValueError
            display = parsed.netloc
            if parsed.path and parsed.path != "/":
                display += parsed.path
            if parsed.query:
                display += "?" + parsed.query
        except Exception:
            display = url
        display = display.rstrip("/")
        max_len = 50
        if len(display) > max_len:
            display = display[:max_len - 3] + "..."
        return f"{display} (URL)" if suffix else display

    def _format_file_display(self, entry):
        if entry.startswith("http://") or entry.startswith("https://"):
            return self._format_url_display(entry)
        return os.path.basename(entry)

    def add_url_to_list(self):
        if not rag_functions:
            messagebox.showinfo("RAG Disabled", "URL ingestion requires RAG. Enable RAG in settings first.", parent=self.files_window)
            return
        if not self.session_id:
            messagebox.showinfo("No Chat Selected", "Please select a chat before attaching a URL.", parent=self.files_window)
            return

        raw_url = simpledialog.askstring("Add URL", "Enter the URL to attach:", parent=self.files_window)
        normalized_url = self._normalize_url(raw_url)
        if not normalized_url:
            if raw_url and raw_url.strip():
                messagebox.showerror("Invalid URL", "Please provide a valid URL (including domain).", parent=self.files_window)
            return
        url = normalized_url

        if url in self.chat_files:
            messagebox.showinfo("Duplicate URL", "This URL is already attached to the chat.", parent=self.files_window)
            return

        self.show_status_message(f"Fetching content from {url}...")
        try:
            text = fetch_url_text(url)
        except Exception as e:
            self.show_status_message(f"Failed to fetch {url}: {e}")
            messagebox.showerror("Fetch Error", f"Failed to fetch content from the URL:\n{e}", parent=self.files_window)
            return

        try:
            rag_functions['add_text_to_chat'](text, source=url, chat_id=self.session_id)
            save_message(self.session_id, "assistant", f"Retrieved and stored content from {url}")
        except Exception as e:
            self.show_status_message(f"Failed to embed URL content: {e}")
            messagebox.showerror("RAG Error", f"Failed to store URL content:\n{e}", parent=self.files_window)
            return

        self.chat_files.append(url)
        self.update_files_listbox()
        self.load_chat_history()
        self.show_status_message(f"URL added: {self._format_url_display(url, suffix=False)}")

    def remove_selected_file(self):
        selection = self.files_listbox.curselection()
        if selection:
            selected_index = selection[0]
            file_path = self.chat_files[selected_index]
            if rag_functions:
                try:
                    if not self.session_id:
                        self.show_status_message("No active chat session. Cannot delete file from RAG.")
                    else:
                        if file_path.startswith("http://") or file_path.startswith("https://"):
                            rag_functions['delete_source_from_chat'](file_path, chat_id=self.session_id)
                            delete_message_by_content(self.session_id, file_path)
                            delete_message_by_content(self.session_id, f"Retrieved and stored content from {file_path}")
                        else:
                            rag_functions['delete_file_from_chat'](file_path, chat_id=self.session_id)
                        self.show_status_message(f"File removed from ChromaDB for chat {self.session_id}.")
                except Exception as e:
                    self.show_status_message(f"Failed to remove file from ChromaDB: {e}")
            del self.chat_files[selected_index]
            self.update_files_listbox()
            self.load_chat_history()

    def update_files_listbox(self):
        if not hasattr(self, "files_listbox") or not self.files_listbox.winfo_exists():
            return
        self.files_listbox.delete(0, tk.END)
        for file_path in self.chat_files:
            display = self._format_file_display(file_path)
            self.files_listbox.insert(tk.END, display)

    def update_files_listbox2(self):
        self.files_listbox.delete(0, tk.END)
        for file_path in self.chat_files:
            display = self._format_file_display(file_path)
            self.files_listbox.insert(tk.END, display)

    def create_files_listbox_tooltip(self):
        tooltip = ToolTip(self.files_listbox)
        self.last_tooltip_index = -1
        def on_motion(event):
            try:
                index = self.files_listbox.index(f"@{event.x},{event.y}")
                if self.last_tooltip_index != index:
                    self.last_tooltip_index = index
                    full_path = self.chat_files[index]
                    tooltip.showtip(full_path)
            except (tk.TclError, IndexError):
                self.last_tooltip_index = -1
                tooltip.hidetip()
        
        def on_leave(event):
            self.last_tooltip_index = -1
            tooltip.hidetip()

        self.files_listbox.bind('<Motion>', on_motion)
        self.files_listbox.bind('<Leave>', on_leave)

    def show_files_listbox_menu(self, event):
        self.close_all_menus()
        try:
            selection_index = self.files_listbox.index(f"@{event.x},{event.y}")
            self.files_listbox.selection_clear(0, tk.END)
            self.files_listbox.selection_set(selection_index)
            self.files_listbox_menu.post(event.x_root, event.y_root)
        except tk.TclError:
            # Click was not on an item
            pass

    def process_new_chat_file(self, file_path):
        if not rag_functions: return
        self.show_status_message(f"Processing file: {os.path.basename(file_path)}")
        try:
            if not self.session_id:
                self.show_status_message("No active chat session. Cannot associate file.")
                return
            rag_functions['add_file_to_chat'](file_path, chat_id=self.session_id)
            self.show_status_message(f"File embedded and associated with chat {self.session_id}.")
        except Exception as e:
            self.show_status_message(f"Failed to embed file: {e}")

    def send_message(self, event=None):
        content = self.input_box.get("1.0", tk.END).strip()

        self.input_box.delete("1.0", tk.END)
        self.update_idletasks()

        # may need to wake up the RAG!
        if rag_functions:
          rag_functions['wake_rag_processor']()

        if not content or not self.session_id:
            return "break"

        active_session_id = self.session_id
        save_message(self.session_id, "user", content)
        save_input_history(self.session_id, content)
        self.message_history = get_input_history(self.session_id)
        self.history_index = len(self.message_history)
        self.current_input_buffer = ""

        selected_server_name = self.server_var.get()
        server_config = self.server_manager.get_server(selected_server_name) if selected_server_name else None
        if not server_config:
            messagebox.showerror(
                "Server Unavailable",
                "The selected server is no longer available. Please choose a different server before sending a message.",
                parent=self
            )
            return "break"

        self.current_server_config = server_config
        set_current_server_config(server_config)

        update_session_server(active_session_id, selected_server_name)

        selected_model = self.model_var.get()
        if selected_model:
            update_session_model(active_session_id, selected_model)

        url_pattern = r'^https?://\S+$'
        if re.match(url_pattern, content) and rag_functions:
            self.load_chat_history()
            self.show_status_message(f"Retrieving {content}...")
            try:
                if not rag_functions['is_rag_loaded']():
                    self.show_status_message("RAG processing initializing...")
                    print("RAG processing initializing...")
                text = fetch_url_text(content)
                rag_functions['add_text_to_chat'](text, source=content, chat_id=self.session_id)
                rag_functions['query_by_chat_id'](self.session_id, text, n_results=1)
                if content not in self.chat_files:
                    self.chat_files.append(content)
                    self.update_files_listbox()
                save_message(self.session_id, "assistant", f"Retrieved and stored content from {content}")
            except Exception as e:
                save_message(self.session_id, "assistant", f"Error retrieving {content}: {e}")
                raise e
            self.load_chat_history()
            return "break"
        
        messages = get_messages(self.session_id)
        message_blocks = [{"role": role, "content": content} for role, content in messages]
        
        system_prompt = self.system_prompt_text.get("1.0", tk.END).strip()
        if system_prompt:
            message_blocks.insert(0, {"role": "system", "content": system_prompt})

        # RAG workflow: If chat has associated files, retrieve context from ChromaDB
        context_block = None
        if rag_functions and self.chat_files:
            if not rag_functions['is_rag_loaded']():
                self.show_status_message("RAG processing initializing...")
                print("RAG processing initializing...")
            try:
                top_k = 5
                rag_results = rag_functions['query_by_chat_id'](self.session_id, content, n_results=top_k)
                if rag_results:
                    context_texts = [r['text'] for r in rag_results]
                    context_block = '\n---\n'.join(context_texts)
                    content_with_context = f"Context:\n{context_block}\n\nUser Query: {content}"
                    for msg in message_blocks:
                        if msg['role'] == 'user':
                            msg['content'] = content_with_context
                            break
            except Exception as e:
                self.show_status_message(f"RAG context retrieval failed: {e}")

        self.load_chat_history()
        
        # Ensure the UI updates to show the user's message before the API call
        self.update_idletasks()

        try:
            send_to_api(
                self.session_name,
                message_blocks,
                self.model_var.get(),
                active_session_id,
                server_config=server_config,
                widget=self.chat_history
            )
            current_model = self.model_var.get()
            update_session_last_model_used(active_session_id, current_model)
            self.last_model_used = current_model
            self.refresh_last_model_label()
        except Exception as e:
            messagebox.showerror("API Error", str(e))

        # After the response, reload the history to show the assistant's message
        self.load_chat_history()
        
        # Auto-summarize session name
        self.summarize_and_rename_session()

        return "break"

    def history_up_wrapper(self, event):
        # Only trigger history if cursor is at the beginning of the input box
        if self.input_box.index(tk.INSERT) == "1.0":
            return self.history_up(event)
    
    def history_down_wrapper(self, event):
        # Only trigger history if cursor is at the end of the input box
        if self.input_box.index(tk.INSERT) == self.input_box.index(tk.END + "-1c"):
            return self.history_down(event)

    def history_up(self, event):
        if not self.message_history:
            return

        # If we're at the current input, buffer it
        if self.history_index == len(self.message_history):
            self.current_input_buffer = self.input_box.get("1.0", tk.END).strip()

        if self.history_index > 0:
            self.history_index -= 1
            self.input_box.delete("1.0", tk.END)
            self.input_box.insert("1.0", self.message_history[self.history_index])
        return "break"

    def history_down(self, event):
        if not self.message_history:
            return

        if self.history_index < len(self.message_history) - 1:
            self.history_index += 1
            self.input_box.delete("1.0", tk.END)
            self.input_box.insert("1.0", self.message_history[self.history_index])
        elif self.history_index == len(self.message_history) - 1:
            # We're at the last item in history, so move to the buffered current input
            self.history_index += 1
            self.input_box.delete("1.0", tk.END)
            self.input_box.insert("1.0", self.current_input_buffer)
        return "break"

    def chat_history_keypress(self, event):
        # Allow copying from the disabled ScrolledText widget
        if event.state == 4 and event.keysym.lower() == 'c': # Ctrl+C
            self.copy_chat_selection()
        return "break"

    def increase_font_size(self, event=None):
        new_size = self.chat_font_size.get() + 1
        self.chat_font_size.set(new_size)
        self.apply_font()
        save_setting("chat_font_size", new_size)

    def decrease_font_size(self, event=None):
        new_size = self.chat_font_size.get() - 1
        if new_size > 0:
            self.chat_font_size.set(new_size)
            self.apply_font()
            save_setting("chat_font_size", new_size)

    def find_dialog(self, event=None):
        self.search_frame.grid(row=1, column=0, sticky="ew", pady=2)
        self.search_entry.focus_set()
        self.search_entry.delete(0, tk.END)
        self.chat_history.tag_remove("search_highlight", "1.0", tk.END)
        self.search_matches = []
        self.current_match_index = -1

    def hide_search(self, event=None):
        self.search_frame.grid_remove()
        self.chat_history.tag_remove("search_highlight", "1.0", tk.END)
        self.chat_history.tag_remove("current_match", "1.0", tk.END)

    def find_next(self, event=None):
        query = self.search_entry.get()
        if not query:
            return

        # If this is a new search
        if not self.search_matches or self.last_search_query != query:
            self.last_search_query = query
            self.search_matches = []
            self.current_match_index = -1
            self.chat_history.tag_remove("search_highlight", "1.0", tk.END)
            
            start_pos = "1.0"
            while True:
                pos = self.chat_history.search(query, start_pos, stopindex=tk.END, nocase=True)
                if not pos:
                    break
                end_pos = f"{pos}+{len(query)}c"
                self.search_matches.append((pos, end_pos))
                self.chat_history.tag_add("search_highlight", pos, end_pos)
                start_pos = end_pos
            
            self.chat_history.tag_config("search_highlight", background="yellow", foreground="black")
            self.chat_history.tag_config("current_match", background="orange", foreground="black")

        if not self.search_matches:
            self.show_status_message(f"'{query}' not found.")
            return

        self.current_match_index = (self.current_match_index + 1) % len(self.search_matches)
        self.highlight_current_match()

    def find_prev(self, event=None):
        if not self.search_matches:
            return

        self.current_match_index = (self.current_match_index - 1 + len(self.search_matches)) % len(self.search_matches)
        self.highlight_current_match()

    def highlight_current_match(self):
        self.chat_history.tag_remove("current_match", "1.0", tk.END)
        if self.current_match_index >= 0:
            start_pos, end_pos = self.search_matches[self.current_match_index]
            self.chat_history.tag_add("current_match", start_pos, end_pos)
            self.chat_history.see(start_pos)

def main():
    global DB_PATH, RECENT_DBS, WINDOW_GEOMETRIES
    parser = argparse.ArgumentParser(description="SlipstreamAI Chat Client")
    parser.add_argument('--db', type=str, help='Path to the chat database file.')
    args = parser.parse_args()
    if args.db:
        DB_PATH = args.db
    RECENT_DBS = load_recent_dbs()
    if not args.db and RECENT_DBS:
        DB_PATH = RECENT_DBS[0]

    if DB_PATH in RECENT_DBS:
        RECENT_DBS.remove(DB_PATH)
    RECENT_DBS.insert(0, DB_PATH)
    RECENT_DBS = RECENT_DBS[:5]
    save_recent_dbs(RECENT_DBS)
    print(f"Using database: {DB_PATH}")
    WINDOW_GEOMETRIES = load_window_geometries()
    # Initialize database first so settings are available
    init_db()
    # Now initialize RAG based on settings
    initialize_rag()
    app = ChatApp()
    geom_state = WINDOW_GEOMETRIES.get(DB_PATH)
    geometry = None
    sash = None
    if isinstance(geom_state, dict):
        geometry = geom_state.get("geometry")
        sash = geom_state.get("sash")
    else:
        geometry = geom_state
    if geometry:
        app.geometry(geometry)
    if sash is not None:
        app.after_idle(lambda: app.apply_sash_position(sash))
    else:
        default_needed = geom_state is None or (isinstance(geom_state, dict) and sash is None)
        if default_needed:
            app.after(200, app.apply_default_sash)
    app.mainloop()

if __name__ == "__main__":
    main()
