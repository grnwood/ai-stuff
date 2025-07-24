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
from markdown import markdown
from html.parser import HTMLParser
from tkinter import PhotoImage
from dotenv import load_dotenv
from tkinter import font
from PIL import Image
from rag.rag_manager import RAGManager
from bs4 import BeautifulSoup
import platform

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
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,/;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    resp = requests.get(url, headers=headers, allow_redirects=True, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    return soup.get_text(separator="\n")

load_dotenv()

APP_NAME="SlipStreamAI"
API_URL = os.getenv("PUBLISHED_API", "http://localhost:3000")
API_SECRET = os.getenv("API_SECRET_TOKEN", "my-secret-token")
PROXY_VERIFY_CERT = os.getenv("PROXY_VERIFY_CERT", "False").lower() == "true"
RAG_IDLE_MINUTES = int(os.getenv("RAG_IDLE_MINUTES", "5"))

# Default database path. This may be overridden via --db on the command line
# and can be changed at runtime from the settings window.
DB_PATH = "chat_sessions.db"

# File used to persist a list of recently opened databases
RECENT_DB_FILE = "recent_dbs.json"
RECENT_DBS = []

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

def get_available_models():
    try:
        print(f"Fetching available models from {API_URL}/mods, PROXY_VERIFY_CERT={PROXY_VERIFY_CERT}")
        response = requests.get(f"{API_URL}/mods", headers={"x-api-secret": API_SECRET},verify=PROXY_VERIFY_CERT)
        response.raise_for_status()
        models = response.json()
        # The structure from the proxy is already a list of model objects
        available_models = sorted([model['id'] for model in models['data']]) #if "gpt" in model['id']])
        return available_models
    except Exception as e:
        print(f"Error fetching models: {e}")
        return ["gpt-3.5-turbo"] # Fallback to a default model

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
                    system_prompt TEXT,
                    parent_id INTEGER,
                    type TEXT DEFAULT 'chat',
                    FOREIGN KEY(parent_id) REFERENCES sessions(id)
                )''')
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

def get_sessions():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, model, system_prompt, parent_id, type FROM sessions ORDER BY id")
    sessions = c.fetchall()
    conn.close()
    return sessions

def create_session(name, model='gpt-3.5-turbo', system_prompt='', type='chat', parent_id=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO sessions (name, model, system_prompt, type, parent_id) VALUES (?, ?, ?, ?, ?)", (name, model, system_prompt, type, parent_id))
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


def update_session_system_prompt(session_id, system_prompt):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE sessions SET system_prompt = ? WHERE id = ?", (system_prompt, session_id))
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

def send_to_api(session_name, messages, model, current_session_id, widget=None, save_message_to_db=True):
    payload = {
        "model": model,
        "messages": messages,
        "stream": True  # Enable streaming
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-secret": API_SECRET
    }

    assistant_full_reply = ""
    if widget:
        widget.configure(state="normal")
        widget.insert(tk.END, "Assistant:\n", ("assistant_tag")) # Start assistant message
        widget.see(tk.END)
        widget.update_idletasks()

    with requests.post(f"{API_URL}/v1/chat/completions", json=payload, headers=headers, stream=True, verify=PROXY_VERIFY_CERT) as resp:
        resp.raise_for_status()
        assistant_full_reply = stream_and_process_response(resp, widget)
    
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
        
        # Manager for optional RAG support using ChromaDB
        self.rag_manager = RAGManager()

        init_db()
        self.session_id = None
        self.session_name = None
        self.message_history = []
        self.history_index = -1
        self.chat_files = []
        self.rag_enabled = get_setting("enable_rag", "True") == "True"
        self.rag_unload_after_id = None
        
        self.theme = tk.StringVar(value=get_setting("theme", "light"))
        self.chat_font = tk.StringVar(value=get_setting("chat_font", "TkDefaultFont"))
        self.chat_font_size = tk.IntVar(value=get_setting("chat_font_size", 10))
        self.ui_font = tk.StringVar(value=get_setting("ui_font", "TkDefaultFont"))
        self.ui_font_size = tk.IntVar(value=get_setting("ui_font_size", 12))
        self.selection_bg = tk.StringVar(value=get_setting("selection_bg", "#b2d7ff"))
        self.selection_fg = tk.StringVar(value=get_setting("selection_fg", "black"))

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

        self.bind("<Control-equal>", self.increase_font_size)
        self.bind("<Control-minus>", self.decrease_font_size)
        self.bind("<Control-f>", self.find_dialog)
        self.search_matches = []
        self.current_match_index = -1
        self.drag_item = None
        self.current_input_buffer = ""

        # Ensure the process exits cleanly when the window is closed
        self.protocol("WM_DELETE_WINDOW", self.on_close)

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
        global DB_PATH, RECENT_DBS

        if not db_path:
            return

        # Normalize the DB path
        db_path = os.path.abspath(db_path)

        DB_PATH = db_path
        if db_path in RECENT_DBS:
            RECENT_DBS.remove(db_path)
        RECENT_DBS.insert(0, db_path)
        RECENT_DBS = RECENT_DBS[:5]
        save_recent_dbs(RECENT_DBS)

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
        # Ensure any RAG-related resources are released
        if hasattr(self, "rag_manager"):
            self.rag_manager.close()
        self.destroy()
        sys.exit(0)

    def on_model_selected(self, event):
        if self.session_id:
            selected_model = self.model_var.get()
            update_session_model(self.session_id, selected_model)

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
        self.drag_item = self.session_tree.identify_row(event.y)
        if self.drag_item:
            self.session_tree.item(self.drag_item, tags="drag_item")

    def on_button_release(self, event):
        if not self.drag_item:
            return
            
        item_under_mouse = self.session_tree.identify_row(event.y)
        
        if item_under_mouse and item_under_mouse != self.drag_item:
            if self.session_tree.item(item_under_mouse, "values")[1] == 'folder':
                # Dropped onto a folder
                self.session_tree.move(self.drag_item, item_under_mouse, 'end')
                drag_id = self.session_tree.item(self.drag_item, "values")[0]
                target_id = self.session_tree.item(item_under_mouse, "values")[0]
                self.update_item_parent(drag_id, target_id)
            else:
                # Dropped between items
                parent = self.session_tree.parent(item_under_mouse)
                index = self.session_tree.index(item_under_mouse)
                self.session_tree.move(self.drag_item, parent, index)
                drag_id = self.session_tree.item(self.drag_item, "values")[0]
                parent_id = self.session_tree.item(parent, "values")[0] if parent else None
                self.update_item_parent(drag_id, parent_id)
        elif not item_under_mouse:
            # Dropped in empty space, move to root
            self.session_tree.move(self.drag_item, "", "end")
            drag_id = self.session_tree.item(self.drag_item, "values")[0]
            self.update_item_parent(drag_id, None)

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
    
    def show_session_context_menu(self, event):
        item = self.session_tree.identify_row(event.y)
        if not item:
            self.whitespace_context_menu.post(event.x_root, event.y_root)
            return
        
        self.session_tree.selection_set(item)
        item_type = self.session_tree.item(item, "values")[1]

        if item_type == 'folder':
            self.session_context_menu.entryconfig("New Chat", state="normal")
        else:
            self.session_context_menu.entryconfig("New Chat", state="disabled")

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

        new_name = tk.simpledialog.askstring("Rename", "Enter new name:", initialvalue=old_name)
        if new_name and new_name != old_name:
            update_session_name(session_id, new_name)
            self.session_tree.item(selected_item, text=new_name)

            if self.session_id == session_id:
                self.session_name = new_name
                self.title(f"{APP_NAME} - {self.session_name}")

    def delete_session(self):
        selection = self.session_tree.selection()
        if not selection:
            return

        selected_item = selection[0]
        session_id, type = self.session_tree.item(selected_item, "values")
        session_id = int(session_id)
        session_name = self.session_tree.item(selected_item, "text")

        if type == 'folder':
            # Simple folder deletion: only if it's empty
            if not self.session_tree.get_children(selected_item):
                if messagebox.askyesno("Delete Folder", f"Are you sure you want to delete the empty folder '{session_name}'?"):
                    delete_session_and_messages(session_id)
                    self.session_tree.delete(selected_item)
            else:
                messagebox.showinfo("Delete Folder", "Cannot delete a folder that is not empty.")
            return

        messages = get_messages(session_id)
        
        do_delete = False
        if not messages: # If the session is empty, delete without confirmation
            do_delete = True
        elif messagebox.askyesno("Delete Session", f"Are you sure you want to delete session '{session_name}' and all its messages?"):
            do_delete = True

        if do_delete:
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
            self.session_tree.delete(selected_item)

            if self.session_id == session_id:
                self.session_id = None
                self.session_name = None
                self.chat_history.configure(state="normal")
                self.chat_history.delete("1.0", tk.END)
                self.chat_history.configure(state="normal")
                self.update_input_widgets_state()

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
        self.left_frame.rowconfigure(4, weight=1)

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

        # --- Model Selection ---
        self.model_label = ttk.Label(self.left_frame, text="Select Model:")
        self.model_label.grid(row=2, column=0, sticky="w", padx=10, pady=(10, 5))
        self.model_var = tk.StringVar()
        self.model_dropdown = ttk.Combobox(self.left_frame, textvariable=self.model_var, state="readonly")
        self.model_dropdown.grid(row=3, column=0, sticky="ew", padx=10, pady=2)
        self.model_dropdown['values'] = get_available_models()
        self.model_dropdown.set("gpt-3.5-turbo")
        self.model_dropdown.bind('<<ComboboxSelected>>', self.on_model_selected)

        self.session_tree = ttk.Treeview(self.left_frame, show="tree")
        self.session_tree.grid(row=4, column=0, sticky="nsew", padx=10, pady=10)
        self.session_tree.bind('<<TreeviewSelect>>', self.select_session)
        self.session_tree.bind('<Button-3>', self.show_session_context_menu)
        self.session_tree.bind("<B1-Motion>", self.move_item)
        self.session_tree.bind("<ButtonPress-1>", self.on_button_press)
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

        self.whitespace_context_menu = tk.Menu(self.session_tree, tearoff=0)
        self.whitespace_context_menu.add_command(label="New Chat", command=lambda: self.new_session(parent_id=None))
        self.whitespace_context_menu.add_command(label="New Folder", command=lambda: self.new_folder(parent_id=None))

        self.new_button = ttk.Button(self.left_frame, text="+ New", command=self.new_session)
        self.new_button.grid(row=5, column=0, sticky="ew", padx=10, pady=(0, 2))

        self.export_button = ttk.Button(self.left_frame, text="Export Chat", command=self.export_chat)
        self.export_button.grid(row=6, column=0, sticky="ew", padx=10, pady=2)

        self.import_button = ttk.Button(self.left_frame, text="Import Chat", command=self.import_chat)
        self.import_button.grid(row=7, column=0, sticky="ew", padx=10, pady=2)

        self.settings_button = ttk.Button(self.left_frame, text="Settings", command=self.open_settings)
        self.settings_button.grid(row=8, column=0, sticky="ew", padx=10, pady=(2, 10))

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

        self.input_container_frame = ttk.Frame(self.main_frame)
        self.input_container_frame.grid(row=1, column=0, sticky="ew")
        self.input_container_frame.columnconfigure(0, weight=1)
        self.input_container_frame.rowconfigure(0, weight=1)
        self.input_container_frame.rowconfigure(1, weight=1)

        self.input_box = tk.Text(
            self.input_container_frame,
            height=5,
            wrap=tk.WORD,
            selectbackground=self.selection_bg.get(),
            selectforeground=self.selection_fg.get()
        )
        self.input_box.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.input_box.bind("<Control-Return>", self.send_message)
        self.input_box.bind("<Up>", self.history_up_wrapper)
        self.input_box.bind("<Down>", self.history_down_wrapper)

        self.send_button = ttk.Button(self.input_container_frame, text="Send", command=self.send_message)
        self.send_button.grid(row=0, column=1, sticky="nsew")

        # Files button directly below Send, no gap
        self.files_button = ttk.Button(self.input_container_frame, text="Files", command=self.open_files_dialog)
        self.files_button.grid(row=1, column=1, sticky="nsew")

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

        # --- Toggle Button for Right Panel ---
        style = ttk.Style()
        style.configure("Small.TButton", padding=1, font=('TkDefaultFont', 7))
        self.toggle_right_panel_button = ttk.Button(self, text="<", command=self.toggle_right_panel, style="Small.TButton")
        self.toggle_right_panel_button.place(relx=1.0, rely=0.0, x=-2, y=2, anchor="ne")

        # --- Status Bar ---
        self.status_bar = ttk.Label(self, text="", anchor=tk.W)
        self.status_bar.grid(row=1, column=0, sticky="ew")

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
            self.export_button.configure(style="Dark.TButton")
            self.import_button.configure(style="Dark.TButton")
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
            self.export_button.configure(style="TButton")
            self.import_button.configure(style="TButton")
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

    def open_settings(self):
        settings_win = tk.Toplevel(self)
        settings_win.title("Settings")
        settings_win.geometry("700x700")

        if self.theme.get() == "dark":
            settings_win.configure(bg="#2b2b2b")
            for widget in settings_win.winfo_children():
                if isinstance(widget, (ttk.Label, ttk.Radiobutton)):
                    widget.configure(style="Dark.TLabel")

        # Theme settings
        ttk.Label(settings_win, text="Theme:").grid(row=0, column=0, sticky="w", pady=5, padx=20)
        
        def on_theme_change():
            save_setting("theme", self.theme.get())
            self.apply_theme()
            # Re-apply theme to settings window
            if self.theme.get() == "dark":
                settings_win.configure(bg="#2b2b2b")
                for widget in settings_win.winfo_children():
                    if isinstance(widget, (ttk.Label, ttk.Radiobutton)):
                        widget.configure(style="Dark.TLabel")
            else:
                settings_win.configure(bg="#f0f0f0")
                for widget in settings_win.winfo_children():
                    if isinstance(widget, (ttk.Label, ttk.Radiobutton)):
                        widget.configure(style="TLabel")


        light_radio = ttk.Radiobutton(settings_win, text="Light", variable=self.theme, value="light", command=on_theme_change)
        light_radio.grid(row=1, column=0, sticky="w", padx=20)

        dark_radio = ttk.Radiobutton(settings_win, text="Dark", variable=self.theme, value="dark", command=on_theme_change)
        dark_radio.grid(row=2, column=0, sticky="w", padx=20)

        # Default model settings
        ttk.Label(settings_win, text="Default Model:").grid(row=3, column=0, sticky="w", pady=5, padx=20)
        
        default_model_var = tk.StringVar(value=get_setting("default_model", "gpt-3.5-turbo"))
        
        def on_default_model_change(*args):
            save_setting("default_model", default_model_var.get())

        default_model_dropdown = ttk.Combobox(settings_win, textvariable=default_model_var, state="readonly")
        default_model_dropdown['values'] = get_available_models()
        default_model_dropdown.grid(row=4, column=0, sticky="ew", padx=20)
        default_model_var.trace_add("write", on_default_model_change)

        # Chat font settings
        ttk.Label(settings_win, text="Chat Font:").grid(row=5, column=0, sticky="w", pady=5, padx=20)
        
        def on_font_change(*args):
            save_setting("chat_font", self.chat_font.get())
            self.apply_font()

        font_families = sorted(font.families())
        font_dropdown = ttk.Combobox(settings_win, textvariable=self.chat_font, state="readonly", values=font_families)
        font_dropdown.grid(row=6, column=0, sticky="ew", padx=20)
        self.chat_font.trace_add("write", on_font_change)

        # Chat font size settings
        ttk.Label(settings_win, text="Chat Font Size:").grid(row=7, column=0, sticky="w", pady=5, padx=20)

        def on_font_size_change(*args):
            save_setting("chat_font_size", self.chat_font_size.get())
            self.apply_font()

        font_size_spinbox = ttk.Spinbox(settings_win, from_=8, to=72, textvariable=self.chat_font_size, command=on_font_size_change)
        font_size_spinbox.grid(row=8, column=0, sticky="ew", padx=20)
        self.chat_font_size.trace_add("write", on_font_size_change)

        # UI font settings
        ttk.Label(settings_win, text="UI Font:").grid(row=9, column=0, sticky="w", pady=5, padx=20)

        def on_ui_font_change(*args):
            save_setting("ui_font", self.ui_font.get())
            self.apply_ui_font()

        ui_font_dropdown = ttk.Combobox(settings_win, textvariable=self.ui_font, state="readonly", values=font_families)
        ui_font_dropdown.grid(row=10, column=0, sticky="ew", padx=20)
        self.ui_font.trace_add("write", on_ui_font_change)

        # UI font size settings
        ttk.Label(settings_win, text="UI Font Size:").grid(row=11, column=0, sticky="w", pady=5, padx=20)

        def on_ui_font_size_change(*args):
            save_setting("ui_font_size", self.ui_font_size.get())
            self.apply_ui_font()

        ui_font_size_spinbox = ttk.Spinbox(settings_win, from_=8, to=72, textvariable=self.ui_font_size, command=on_ui_font_size_change)
        ui_font_size_spinbox.grid(row=12, column=0, sticky="ew", padx=20)
        self.ui_font_size.trace_add("write", on_ui_font_size_change)

        ttk.Label(settings_win, text="Selection Background:").grid(row=13, column=0, sticky="w", pady=5, padx=20)

        def choose_sel_bg():
            color = colorchooser.askcolor(initialcolor=self.selection_bg.get())[1]
            if color:
                self.selection_bg.set(color)

        bg_frame = ttk.Frame(settings_win)
        bg_frame.grid(row=14, column=0, sticky="ew", padx=20)
        ttk.Entry(bg_frame, textvariable=self.selection_bg).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(bg_frame, text="Pick", command=choose_sel_bg).pack(side=tk.LEFT, padx=5)

        ttk.Label(settings_win, text="Selection Foreground:").grid(row=15, column=0, sticky="w", pady=5, padx=20)

        def choose_sel_fg():
            color = colorchooser.askcolor(initialcolor=self.selection_fg.get())[1]
            if color:
                self.selection_fg.set(color)

        fg_frame = ttk.Frame(settings_win)
        fg_frame.grid(row=16, column=0, sticky="ew", padx=20)
        ttk.Entry(fg_frame, textvariable=self.selection_fg).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(fg_frame, text="Pick", command=choose_sel_fg).pack(side=tk.LEFT, padx=5)

        def on_selection_color_change(*args):
            save_setting("selection_bg", self.selection_bg.get())
            save_setting("selection_fg", self.selection_fg.get())
            self.apply_selection_colors()

        self.selection_bg.trace_add("write", on_selection_color_change)
        self.selection_fg.trace_add("write", on_selection_color_change)

        # Enable RAG setting
        ttk.Label(settings_win, text="Enable RAG (requires restart):").grid(row=17, column=0, sticky="w", pady=5, padx=20)
        rag_var = tk.BooleanVar(value=self.rag_enabled)
        def on_rag_toggle():
            save_setting("enable_rag", rag_var.get())
            messagebox.showinfo("Restart Required", "Please restart the application for the RAG setting to take effect.", parent=settings_win)
        ttk.Checkbutton(settings_win, variable=rag_var, command=on_rag_toggle).grid(row=18, column=0, sticky="w", padx=20)

    def export_chat(self):
        if not self.session_id:
            messagebox.showinfo("Export Chat", "No session selected to export.")
            return

        messages = get_messages(self.session_id)
        
        # Get the current session's details
        current_session_info = None
        for _id, name, model, system_prompt, parent_id, type in get_sessions():
            if _id == self.session_id:
                current_session_info = {
                    "model": model, 
                    "messages": messages,
                    "system_prompt": system_prompt
                }
                break
        
        if not current_session_info:
            messagebox.showerror("Export Error", "Could not retrieve current session details.")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.* ")],
            initialfile=f"{self.session_name.replace(' ', '_')}_chat.json"
        )

        if file_path:
            try:
                with open(file_path, 'w') as f:
                    json.dump(current_session_info, f, indent=4)
                messagebox.showinfo("Export Chat", "Chat exported successfully!")
            except Exception as e:
                messagebox.showerror("Export Error", f"Failed to export chat: {e}")

    def import_chat(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.* ")]
        )

        if file_path:
            try:
                with open(file_path, 'r') as f:
                    imported_data = json.load(f)

                imported_model = "gpt-3.5-turbo"
                imported_messages = []
                imported_system_prompt = ""

                if isinstance(imported_data, dict) and "messages" in imported_data:
                    imported_model = imported_data.get("model", "gpt-3.5-turbo")
                    imported_messages = imported_data["messages"]
                    imported_system_prompt = imported_data.get("system_prompt", "")
                elif isinstance(imported_data, list):
                    imported_messages = imported_data
                else:
                    raise ValueError("Invalid JSON format. Expected a list of messages or a dictionary with 'model' and 'messages'.")

                default_name = os.path.splitext(os.path.basename(file_path))[0]
                new_session_name = tk.simpledialog.askstring(
                    "Import Chat",
                    "Enter a name for the new session:",
                    initialvalue=default_name
                )
                
                if not new_session_name:
                    return

                parent_id = None
                selection = self.session_tree.selection()
                if selection:
                    selected_item = selection[0]
                    item_type = self.session_tree.item(selected_item, "values")[1]
                    if item_type == 'folder':
                        parent_id = self.session_tree.item(selected_item, "values")[0]

                session_id = create_session(new_session_name, imported_model, imported_system_prompt, parent_id=parent_id)
                for role, content in imported_messages:
                    save_message(session_id, role, content)

                self.load_sessions()
                
                new_item = self.find_tree_item_by_id(session_id)
                if new_item:
                    self.session_tree.selection_set(new_item)
                    self.session_tree.focus(new_item)
                    self.select_session(None)

                if imported_model in get_available_models():
                    self.model_var.set(imported_model)
                else:
                    self.model_var.set("gpt-3.5-turbo")

                messagebox.showinfo("Import Chat", "Chat imported successfully!")

            except json.JSONDecodeError:
                messagebox.showerror("Import Error", "Invalid JSON file.")
            except ValueError as e:
                messagebox.showerror("Import Error", f"Error importing chat: {e}")
            except Exception as e:
                messagebox.showerror("Import Error", f"An unexpected error occurred: {e}")

    def new_folder(self, parent_id=None):
        name = tk.simpledialog.askstring("New Folder", "Enter folder name:")
        if name:
            db_parent_id = int(parent_id) if parent_id is not None else None
            session_id = create_session(name, type='folder', parent_id=db_parent_id)
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
            for _id, name, model, system_prompt, s_parent_id, type in sessions:
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

        self.schedule_rag_unload()
        
        if type == 'folder':
            self.session_id = None
            self.session_name = None
            self.title("SlipstreamAI Client")
            self.chat_history.configure(state="normal")
            self.chat_history.delete("1.0", tk.END)
            self.chat_history.configure(state="normal")
            self.update_input_widgets_state()
            return

        for sid, name, model, system_prompt, parent_id, stype in get_sessions():
            if sid == _id:
                self.session_name = name
                self.session_id = _id
                self.title(f"{APP_NAME} - {self.session_name}")
                self.model_var.set(model)
                
                # Load system prompt
                self.system_prompt_text.delete("1.0", tk.END)
                if system_prompt:
                    self.system_prompt_text.insert("1.0", system_prompt)

                if rag_functions:
                    self.chat_files = rag_functions['get_files_for_chat'](self.session_id)
                else:
                    self.chat_files = []
                self.load_chat_history()
                self.message_history = get_input_history(self.session_id)
                self.history_index = len(self.message_history)
                self.current_input_buffer = ""
                self.update_input_widgets_state()
                break
        else:
            self.title(f"{APP_NAME}")
            self.update_input_widgets_state()
            return

    def get_session_id_by_name(self, name):
        for _id, s_name, model, system_prompt, parent_id, type in get_sessions():
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
        default_model = get_setting("default_model", "gpt-3.5-turbo")
        
        if parent_id is None:
            selection = self.session_tree.selection()
            if selection:
                selected_item = selection[0]
                item_type = self.session_tree.item(selected_item, "values")[1]
                if item_type == 'folder':
                    parent_id = self.session_tree.item(selected_item, "values")[0]

        db_parent_id = int(parent_id) if parent_id is not None else None
        session_id = create_session(name, default_model, parent_id=db_parent_id)
        
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

    def schedule_rag_unload(self):
        if not rag_functions or not rag_functions.get('is_rag_loaded'):
            return
        if self.rag_unload_after_id:
            self.after_cancel(self.rag_unload_after_id)
        timeout_ms = RAG_IDLE_MINUTES * 60 * 1000
        self.rag_unload_after_id = self.after(timeout_ms, self.unload_rag)

    def unload_rag(self):
        if not rag_functions or not rag_functions.get('is_rag_loaded'):
            return
        try:
            rag_functions['unload_rag_processor']()
            print("RAG unloaded to free memory...")
            self.show_status_message("RAG unloaded to free memory...")
            if self.session_id:
                save_message(self.session_id, "assistant", "RAG unloaded to free memory...")
                self.load_chat_history()
        finally:
            self.rag_unload_after_id = None

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
            self.schedule_rag_unload()

        self.load_chat_history()
        self.schedule_rag_unload()
        self.update_idletasks()

        try:
            send_to_api(self.session_name, message_blocks, self.model_var.get(), active_session_id, self.chat_history)
        except Exception as e:
            messagebox.showerror("API Error", str(e))

        self.load_chat_history()

        self.schedule_rag_unload()

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
            new_session_name = send_to_api(
                "New Discussion", 
                messages, 
                "gpt-3.5-turbo", 
                self.session_id, 
                widget=None, 
                save_message_to_db=False
            ).strip().strip('"') # Strip quotes from the response

            if not new_session_name:
                new_session_name = "New Discussion"

            # Create a new session with the generated title
            new_session_id = create_session(new_session_name, self.model_var.get(), self.system_prompt_text.get("1.0", tk.END).strip())
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

    def summarize_and_rename_session(self):
        if not self.session_id or not self.session_name:
            return

        messages = get_messages(self.session_id)
        if len(messages) < 2: # Need at least one user and one assistant message
            return

        conversation = ""
        for role, content in messages:
            conversation += f"{role.title()}: {content}\n"

        prompt = f"The current chat session name is '{self.session_name}'. Summarize the following conversation in 5 words or less. This summary will be used as the new session name. Only change the name if a significant topic shift occurs. Do not use quotes in the summary.\n\nConversation:\n{conversation}"

        try:
            messages_for_summary = [
                {"role": "system", "content": "You are a helpful assistant that summarizes chat sessions for use as a new session name."},
                {"role": "user", "content": prompt}
            ]
            
            # Call send_to_api without a widget to get the response directly
            new_name = send_to_api(
                self.session_name, 
                messages_for_summary, 
                "gpt-3.5-turbo", 
                self.session_id, 
                widget=None,
                save_message_to_db=False
            ).strip().strip('"') # Strip quotes from the response

            if new_name and new_name != self.session_name and len(new_name.split()) <= 5:
                item_to_select = self.find_tree_item_by_id(self.session_id)
                if not item_to_select:
                    return 

                update_session_name(self.session_id, new_name)
                self.session_name = new_name
                
                # Update the name in the listbox directly
                self.session_tree.item(item_to_select, text=new_name)
                self.title(f"{APP_NAME} - {self.session_name}")


        except Exception as e:
            print(f"Error summarizing session: {e}")

    def close_files_dialog(self):
        if hasattr(self, 'files_window') and self.files_window.winfo_exists():
            self.files_window.grab_release()
            self.files_window.destroy()

    def open_files_dialog(self):
        if hasattr(self, 'files_window') and self.files_window.winfo_exists():
            self.files_window.lift()
            return

        self.files_window = tk.Toplevel(self)
        self.files_window.title("Attached Files")
        self.files_window.geometry("400x300")

        self.files_window.transient(self)
        self.files_window.grab_set()
        self.files_window.protocol("WM_DELETE_WINDOW", self.close_files_dialog)

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

        remove_button = ttk.Button(button_frame, text="Remove", command=self.remove_selected_file)
        remove_button.pack(side=tk.LEFT)

        self.files_listbox_menu = tk.Menu(self.files_listbox, tearoff=0)
        self.files_listbox_menu.add_command(label="Remove", command=self.remove_selected_file)
        self.files_listbox.bind("<Button-3>", self.show_files_listbox_menu)

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
            if file_path.startswith("http://") or file_path.startswith("https://"):
                display = f"URL:{file_path}"
            else:
                display = os.path.basename(file_path)
            self.files_listbox.insert(tk.END, display)

    def update_files_listbox2(self):
        self.files_listbox.delete(0, tk.END)
        for file_path in self.chat_files:
            if file_path.startswith("http://") or file_path.startswith("https://"):
                display = f"URL:{file_path}"
            else:
                display = os.path.basename(file_path)
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
            self.schedule_rag_unload()
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
            self.schedule_rag_unload()
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
            self.schedule_rag_unload()

        self.load_chat_history()
        
        # Ensure the UI updates to show the user's message before the API call
        self.update_idletasks()

        try:
            send_to_api(self.session_name, message_blocks, self.model_var.get(), active_session_id, self.chat_history)
        except Exception as e:
            messagebox.showerror("API Error", str(e))
        
        # After the response, reload the history to show the assistant's message
        self.load_chat_history()
        
        # Auto-summarize session name
        self.summarize_and_rename_session()

        self.schedule_rag_unload()

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
    global DB_PATH, RECENT_DBS
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
    # Initialize database first so settings are available
    init_db()
    # Now initialize RAG based on settings
    initialize_rag()
    app = ChatApp()
    app.mainloop()

if __name__ == "__main__":
    main()