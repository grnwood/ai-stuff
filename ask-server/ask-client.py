import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from tkinter.scrolledtext import ScrolledText
import requests
import os
import json
import sqlite3
from markdown import markdown
from html.parser import HTMLParser
from dotenv import load_dotenv
from tkinter import font

load_dotenv()

APP_NAME="SlipStreamAI"
API_URL = os.getenv("OPENAI_PROXY_URL", "http://localhost:3000")
API_SECRET = os.getenv("API_SECRET_TOKEN", "my-secret-token")
DB_PATH = "chat_sessions.db"

def get_available_models():
    try:
        response = requests.get(f"{API_URL}/mods", headers={"x-api-secret": API_SECRET})
        response.raise_for_status()
        models = response.json()
        # The structure from the proxy is already a list of model objects
        available_models = sorted([model['id'] for model in models['data'] if "gpt" in model['id']])
        return available_models
    except Exception as e:
        print(f"Error fetching models: {e}")
        return ["gpt-3.5-turbo"] # Fallback to a default model

# --- Database ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
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
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
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
                            if widget:
                                widget.configure(state="normal")
                                widget.insert(tk.END, content_chunk)
                                widget.configure(state="disabled")
                                widget.see(tk.END)
                                widget.update_idletasks()
                except json.JSONDecodeError:
                    print(f"Skipping non-JSON line: {decoded_line}")
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
        widget.configure(state="disabled")
        widget.see(tk.END)
        widget.update_idletasks()

    with requests.post(f"{API_URL}/v1/chat/completions", json=payload, headers=headers, stream=True) as resp:
        resp.raise_for_status()
        assistant_full_reply = stream_and_process_response(resp, widget)
    
    # Save the complete assistant reply after streaming is done
    if save_message_to_db:
        save_message(current_session_id, "assistant", assistant_full_reply)
    return assistant_full_reply


# --- Markdown to Plaintext Converter ---
class HTMLToText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = ""

    def handle_data(self, data):
        self.text += data

    def get_text(self):
        return self.text.strip()

def markdown_to_text(md):
    html = markdown(md)
    parser = HTMLToText()
    parser.feed(html)
    return parser.get_text()

class ToolTip:
    def __init__(self, widget):
        self.widget = widget
        self.tip_window = None
        self.id = None
        self.x = self.y = 0

    def showtip(self, text):
        "Display text in tooltip window"
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

        init_db()
        self.session_id = None
        self.session_name = None
        self.message_history = []
        self.history_index = -1
        
        self.theme = tk.StringVar(value=get_setting("theme", "light"))
        self.chat_font = tk.StringVar(value=get_setting("chat_font", "TkDefaultFont"))
        self.chat_font_size = tk.IntVar(value=get_setting("chat_font_size", 10))
        self.ui_font_size = tk.IntVar(value=get_setting("ui_font_size", 12))

        self.build_gui()
        self.apply_theme()
        self.apply_font()
        self.apply_ui_font()
        self.load_sessions()
        self.update_input_widgets_state()

        self.bind("<Control-equal>", self.increase_font_size)
        self.bind("<Control-minus>", self.decrease_font_size)
        self.bind("<Control-f>", self.find_dialog)
        self.search_matches = []
        self.current_match_index = -1
        self.drag_item = None
        self.current_input_buffer = ""

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

    def on_button_release(self, event):
        if not self.drag_item:
            return
            
        item = self.session_tree.identify_row(event.y)
        
        if item and item != self.drag_item:
            if self.session_tree.item(item, "values")[1] == 'folder':
                self.session_tree.move(self.drag_item, item, 'end')
                drag_id = self.session_tree.item(self.drag_item, "values")[0]
                target_id = self.session_tree.item(item, "values")[0]
                self.update_item_parent(drag_id, target_id)
            else:
                parent = self.session_tree.parent(item)
                index = self.session_tree.index(item)
                self.session_tree.move(self.drag_item, parent, index)
                drag_id = self.session_tree.item(self.drag_item, "values")[0]
                parent_id = self.session_tree.item(parent, "values")[0] if parent else None
                self.update_item_parent(drag_id, parent_id)
        elif not item:
            self.session_tree.move(self.drag_item, "", "end")
            drag_id = self.session_tree.item(self.drag_item, "values")[0]
            self.update_item_parent(drag_id, None)

        self.drag_item = None
        self.clear_drop_indicator()

    def move_item(self, event):
        if not self.drag_item:
            return
        
        self.clear_drop_indicator()
        item = self.session_tree.identify_row(event.y)
        
        if item:
            if self.session_tree.item(item, "values")[1] == 'folder':
                self.session_tree.item(item, tags="drop_target")
            else:
                self.session_tree.selection_set(item)

    def clear_drop_indicator(self):
        for item in self.session_tree.get_children(""):
            self.session_tree.item(item, tags="")
            self.clear_tags_recursively(item)

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
        try:
            index = self.session_list.curselection()[0]
            old_name = self.session_list.get(index)
            session_id = self.get_session_id_by_name(old_name)

            new_name = tk.simpledialog.askstring("Rename Session", "Enter new session name:", initialvalue=old_name)
            if new_name and new_name != old_name:
                update_session_name(session_id, new_name)
                self.load_sessions()
                if self.session_id == session_id:
                    self.session_name = new_name
        except IndexError:
            pass

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
        if not messages: # If the session is empty, delete without confirmation
            delete_session_and_messages(session_id)
            self.session_tree.delete(selected_item)
        elif messagebox.askyesno("Delete Session", f"Are you sure you want to delete session '{session_name}' and all its messages?"):
            delete_session_and_messages(session_id)
            self.session_tree.delete(selected_item)

        if self.session_id == session_id:
            self.session_id = None
            self.session_name = None
            self.chat_history.configure(state="normal")
            self.chat_history.delete("1.0", tk.END)
            self.chat_history.configure(state="disabled")
            self.update_input_widgets_state()

    def build_gui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

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
        self.left_frame.rowconfigure(2, weight=1)

        self.model_label = ttk.Label(self.left_frame, text="Select Model:")
        self.model_label.grid(row=0, column=0, sticky="w", padx=10, pady=(10, 5))
        self.model_var = tk.StringVar()
        self.model_dropdown = ttk.Combobox(self.left_frame, textvariable=self.model_var, state="readonly")
        self.model_dropdown.grid(row=1, column=0, sticky="ew", padx=10, pady=2)
        self.model_dropdown['values'] = get_available_models()
        self.model_dropdown.set("gpt-3.5-turbo")
        self.model_dropdown.bind('<<ComboboxSelected>>', self.on_model_selected)

        self.session_tree = ttk.Treeview(self.left_frame, show="tree")
        self.session_tree.grid(row=2, column=0, sticky="nsew", padx=10, pady=10)
        self.session_tree.bind('<<TreeviewSelect>>', self.select_session)
        self.session_tree.bind('<Button-3>', self.show_session_context_menu)
        self.session_tree.bind("<B1-Motion>", self.move_item)
        self.session_tree.bind("<ButtonPress-1>", self.on_button_press)
        self.session_tree.bind("<ButtonRelease-1>", self.on_button_release)

        self.session_context_menu = tk.Menu(self.session_tree, tearoff=0)
        self.session_context_menu.add_command(label="New Chat", command=self.new_chat_in_folder)
        self.session_context_menu.add_command(label="New Folder", command=self.new_folder)
        self.session_context_menu.add_command(label="Rename", command=self.rename_session)
        self.session_context_menu.add_command(label="Delete", command=self.delete_session)

        self.whitespace_context_menu = tk.Menu(self.session_tree, tearoff=0)
        self.whitespace_context_menu.add_command(label="New Chat", command=lambda: self.new_session(parent_id=None))
        self.whitespace_context_menu.add_command(label="New Folder", command=lambda: self.new_folder(parent_id=None))

        self.new_button = ttk.Button(self.left_frame, text="+ New", command=self.new_session)
        self.new_button.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 2))

        self.export_button = ttk.Button(self.left_frame, text="Export Chat", command=self.export_chat)
        self.export_button.grid(row=4, column=0, sticky="ew", padx=10, pady=2)

        self.import_button = ttk.Button(self.left_frame, text="Import Chat", command=self.import_chat)
        self.import_button.grid(row=5, column=0, sticky="ew", padx=10, pady=2)

        self.settings_button = ttk.Button(self.left_frame, text="Settings", command=self.open_settings)
        self.settings_button.grid(row=6, column=0, sticky="ew", padx=10, pady=(2, 10))

        # --- Main Chat Area ---
        self.main_frame = ttk.Frame(self.left_paned_window)
        self.left_paned_window.add(self.main_frame, weight=4)
        self.main_frame.rowconfigure(0, weight=1)
        self.main_frame.columnconfigure(0, weight=1)

        self.chat_history = ScrolledText(self.main_frame, wrap=tk.WORD, padx=10)
        self.chat_history.grid(row=0, column=0, sticky="nsew")
        self.chat_history.bind("<KeyPress>", lambda e: "break")

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

        self.chat_history_menu = tk.Menu(self.chat_history, tearoff=0)
        self.chat_history_menu.add_command(label="Copy", command=self.copy_chat_selection)
        self.chat_history.bind("<Button-3>", self.show_chat_context_menu)

        self.selection_context_menu = tk.Menu(self.chat_history, tearoff=0)
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

        self.input_box = tk.Text(self.input_container_frame, height=5, wrap=tk.WORD)
        self.input_box.grid(row=0, column=0, sticky="ew")
        self.input_box.bind("<Control-Return>", self.send_message)
        self.input_box.bind("<Up>", self.history_up)
        self.input_box.bind("<Down>", self.history_down)

        self.send_button = ttk.Button(self.input_container_frame, text="Send", command=self.send_message)
        self.send_button.grid(row=0, column=1, sticky="e")

        # --- Right Panel (System Prompt) ---
        self.right_frame = ttk.Frame(self.main_paned_window, width=250)
        self.right_frame.columnconfigure(0, weight=1)
        self.right_frame.rowconfigure(2, weight=1)
        
        self.logo_frame = ttk.Frame(self.right_frame)
        self.logo_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        self.logo_frame.columnconfigure(0, weight=1)

       
        self.system_prompt_label = ttk.Label(self.right_frame, text="System Prompt:")
        self.system_prompt_label.grid(row=1, column=0, sticky="w", padx=5, pady=5)
        
        self.system_prompt_text = ScrolledText(self.right_frame, wrap=tk.WORD, height=10)
        self.system_prompt_text.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)
        self.system_prompt_text.bind("<<Modified>>", self.on_system_prompt_modified)

        # --- Toggle Button for Right Panel ---
        self.toggle_right_panel_button = ttk.Button(self, text="<", command=self.toggle_right_panel)
        self.toggle_right_panel_button.place(relx=1.0, rely=0.5, anchor="e")

        # --- Status Bar ---
        self.status_bar = ttk.Label(self, text="", anchor=tk.W)
        self.status_bar.grid(row=1, column=0, sticky="ew")

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

    def on_system_prompt_modified(self, event):
        if self.session_id:
            # Use a flag to prevent recursive calls
            if not hasattr(self, '_system_prompt_updating') or not self._system_prompt_updating:
                self._system_prompt_updating = True
                system_prompt = self.system_prompt_text.get("1.0", tk.END).strip()
                update_session_system_prompt(self.session_id, system_prompt)
                self.system_prompt_text.edit_modified(False) # Reset modified flag
                self._system_prompt_updating = False

    def apply_theme(self):
        theme = self.theme.get()
        s = ttk.Style()
        if theme == "dark":
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
            s.configure("Dark.TButton", background="#4f5254", foreground="white")
            s.map("Dark.TButton", background=[('active', '#6f7274'), ('!disabled', '#4f5254')], foreground=[('!disabled', 'white')])
            s.configure("Dark.Treeview", background="#3c3f41", foreground="white", fieldbackground="#3c3f41")
            s.map("Dark.Treeview", background=[('selected', '#4f5254')], foreground=[('selected', 'white')])
            if os.name == 'nt':
                s.layout("Dark.TButton", [
                    ("Button.border", {"children":
                        [("Button.padding", {"children":
                            [("Button.label", {"side": "left", "expand": 1})]
                        })]
                    })
                ])
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
            s.configure("Treeview", background="white", foreground="black", fieldbackground="white")
            s.map("Treeview", background=[('selected', '#0078d7')], foreground=[('selected', 'white')])

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
        ui_font_size = self.ui_font_size.get()
        style = ttk.Style()
        style.configure("TLabel", font=(None, ui_font_size))
        style.configure("TButton", font=(None, ui_font_size))
        style.configure("TCombobox", font=(None, ui_font_size))
        style.configure("Treeview", font=(None, ui_font_size), rowheight=int(ui_font_size * 2.5))
        self.system_prompt_text.configure(font=(None, ui_font_size))

    def open_settings(self):
        settings_win = tk.Toplevel(self)
        settings_win.title("Settings")
        settings_win.geometry("300x300")

        if self.theme.get() == "dark":
            settings_win.configure(bg="#2b2b2b")
            # Apply dark theme to all widgets in the settings window
            for widget in settings_win.winfo_children():
                if isinstance(widget, (ttk.Label, ttk.Radiobutton)):
                    widget.configure(style="Dark.TLabel")
        
        # Theme settings
        ttk.Label(settings_win, text="Theme:").pack(pady=5)
        
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
        light_radio.pack(anchor=tk.W, padx=20)
        
        dark_radio = ttk.Radiobutton(settings_win, text="Dark", variable=self.theme, value="dark", command=on_theme_change)
        dark_radio.pack(anchor=tk.W, padx=20)

        # Default model settings
        ttk.Label(settings_win, text="Default Model:").pack(pady=5)
        
        default_model_var = tk.StringVar(value=get_setting("default_model", "gpt-3.5-turbo"))
        
        def on_default_model_change(*args):
            save_setting("default_model", default_model_var.get())

        default_model_dropdown = ttk.Combobox(settings_win, textvariable=default_model_var, state="readonly")
        default_model_dropdown['values'] = get_available_models()
        default_model_dropdown.pack(fill=tk.X, padx=20)
        default_model_var.trace_add("write", on_default_model_change)

        # Chat font settings
        ttk.Label(settings_win, text="Chat Font:").pack(pady=5)
        
        def on_font_change(*args):
            save_setting("chat_font", self.chat_font.get())
            self.apply_font()

        font_families = sorted(font.families())
        font_dropdown = ttk.Combobox(settings_win, textvariable=self.chat_font, state="readonly", values=font_families)
        font_dropdown.pack(fill=tk.X, padx=20)
        self.chat_font.trace_add("write", on_font_change)

        # Chat font size settings
        ttk.Label(settings_win, text="Chat Font Size:").pack(pady=5)

        def on_font_size_change(*args):
            save_setting("chat_font_size", self.chat_font_size.get())
            self.apply_font()

        font_size_spinbox = ttk.Spinbox(settings_win, from_=8, to=72, textvariable=self.chat_font_size, command=on_font_size_change)
        font_size_spinbox.pack(fill=tk.X, padx=20)
        self.chat_font_size.trace_add("write", on_font_size_change)

        # UI font size settings
        ttk.Label(settings_win, text="UI Font Size:").pack(pady=5)

        def on_ui_font_size_change(*args):
            save_setting("ui_font_size", self.ui_font_size.get())
            self.apply_ui_font()

        ui_font_size_spinbox = ttk.Spinbox(settings_win, from_=8, to=72, textvariable=self.ui_font_size, command=on_ui_font_size_change)
        ui_font_size_spinbox.pack(fill=tk.X, padx=20)
        self.ui_font_size.trace_add("write", on_ui_font_size_change)

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

                new_session_name = tk.simpledialog.askstring("Import Chat", "Enter a name for the new session:",
                                                              initialvalue=f"Imported Chat {len(get_sessions()) + 1}")
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
            session_id = create_session(name, type='folder', parent_id=parent_id)
            parent_node = self.find_tree_item_by_id(parent_id) if parent_id else ""
            self.session_tree.insert(parent_node, "end", text=name, values=(session_id, 'folder'))

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
                    is_open = _id in open_folders
                    node = self.session_tree.insert(parent_node, "end", text=name, values=(_id, type), open=is_open)
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
            self.title("SlipstreamAI Client")
            self.chat_history.configure(state="normal")
            self.chat_history.delete("1.0", tk.END)
            self.chat_history.configure(state="disabled")
            self.update_input_widgets_state()
            return

        for sid, name, model, system_prompt, parent_id, stype in get_sessions():
            if sid == _id:
                self.session_name = name
                self.session_id = _id
                self.title(f"{APP_NAME} - {self.session_name}")
                self.model_var.set(model)
                
                # Load system prompt
                self._system_prompt_updating = True # Set flag to prevent saving on load
                self.system_prompt_text.delete("1.0", tk.END)
                if system_prompt:
                    self.system_prompt_text.insert("1.0", system_prompt)
                self.system_prompt_text.edit_modified(False) # Reset modified flag
                self._system_prompt_updating = False

                self.load_chat_history()
                self.message_history = get_input_history(self.session_id)
                self.history_index = len(self.message_history)
                self.current_input_buffer = ""
                self.update_input_widgets_state()
                break
        else:
            self.title(f"{APP.NAME}")
            self.update_input_widgets_state()
            return

    def get_session_id_by_name(self, name):
        for _id, s_name, model, system_prompt, parent_id, type in get_sessions():
            if s_name == name:
                return _id
        return None

    def find_tree_item_by_id(self, target_id):
        def search_children(parent_item):
            for item in self.session_tree.get_children(parent_item):
                item_values = self.session_tree.item(item, "values")
                if item_values and int(item_values[0]) == target_id:
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
            self.status_bar.config(text="Please select or create a chat session.")
        else:
            self.input_box.configure(state="normal")
            self.send_button.configure(state="normal")
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

        session_id = create_session(name, default_model, parent_id=parent_id)
        
        parent_node = self.find_tree_item_by_id(int(parent_id)) if parent_id else ""
        new_item = self.session_tree.insert(parent_node, "end", text=name, values=(session_id, 'chat'))
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
        if self.chat_history.tag_ranges("sel"):
            self.selection_context_menu.post(event.x_root, event.y_root)
        else:
            self.chat_history_menu.post(event.x_root, event.y_root)

    def process_selection(self, action):
        try:
            selected_text = self.chat_history.get(tk.SEL_FIRST, tk.SEL_LAST)
            if not selected_text:
                return

            prompt = ""
            if action == "summarize":
                prompt = f"Summarize the following text:\n\n{selected_text}"
            elif action == "tldr":
                prompt = f"Provide a TL;DR version of the following text:\n\n{selected_text}"
            elif action == "explain_simple":
                prompt = f"Explain the following text in simpler terms:\n\n{selected_text}"
            elif action == "explain_more":
                prompt = f"Tell me more about the following text:\n\n{selected_text}"
            elif action == "explain_detail":
                prompt = f"Add more detail and examples to the following text:\n\n{selected_text}"
            elif action == "rewrite_rephrase":
                prompt = f"Rephrase the following text:\n\n{selected_text}"
            elif action == "rewrite_formal":
                prompt = f"Make the following text more formal:\n\n{selected_text}"
            elif action == "rewrite_informal":
                prompt = f"Make the following text more informal:\n\n{selected_text}"
            elif action == "rewrite_professional":
                prompt = f"Make the following text more professional:\n\n{selected_text}"
            elif action == "rewrite_improve":
                prompt = f"Improve the grammar and style of the following text:\n\n{selected_text}"
            elif action == "translate_english":
                prompt = f"Translate the following text to English:\n\n{selected_text}"
            elif action == "translate_detect":
                prompt = f"Detect the language of the following text and translate it to English:\n\n{selected_text}"
            elif action == "analyze_sentiment":
                prompt = f"Analyze the sentiment and tone of the following text:\n\n{selected_text}"
            elif action == "analyze_bias":
                prompt = f"Identify any assumptions or bias in the following text:\n\n{selected_text}"
            elif action == "analyze_topic":
                prompt = f"Classify the topic of the following text:\n\n{selected_text}"
            elif action == "ask_generate":
                prompt = f"Generate questions from the following text:\n\n{selected_text}"
            elif action == "ask_what_questions":
                prompt = f"What questions can I ask about the following text?:\n\n{selected_text}"
            elif action == "extract_key_points":
                prompt = f"Highlight the key points in the following text:\n\n{selected_text}"
            elif action == "extract_entities":
                prompt = f"Extract named entities (people, places, dates, etc.) from the following text:\n\n{selected_text}"
            elif action == "extract_action_items":
                prompt = f"Pull out any action items from the following text:\n\n{selected_text}"
            elif action == "expand_continue":
                prompt = f"Continue writing from the following text:\n\n{selected_text}"
            elif action == "expand_follow_up":
                prompt = f"Generate a follow-up paragraph, story, or argument based on the following text:\n\n{selected_text}"
            elif action == "define_terms":
                prompt = f"Define the following term(s):\n\n{selected_text}"
            elif action == "define_context":
                prompt = f"Provide background or context for the following text:\n\n{selected_text}"
            elif action == "respond_reply":
                prompt = f"Write a reply or response to the following text:\n\n{selected_text}"
            elif action == "respond_discuss":
                # This action will be handled differently, as it creates a new session
                self.start_discussion_from_selection()
                return

            messages = [{"role": "user", "content": prompt}]
            
            assistant_full_reply = send_to_api(
                self.session_name, 
                messages, 
                self.model_var.get(), 
                self.session_id, 
                widget=self.chat_history, 
                save_message_to_db=True
            )
            if assistant_full_reply:
                self.summarize_and_rename_session()

        except tk.TclError:
            # This can happen if there is no selection
            pass
        except Exception as e:
            messagebox.showerror("Error", f"An unexpected error occurred: {e}")

    def start_discussion_from_selection(self):
        try:
            selected_text = self.chat_history.get(tk.SEL_FIRST, tk.SEL_LAST)
            if not selected_text:
                return

            # Summarize the selected text to create a title for the new session
            prompt = f"Summarize the following text in 5 words or less to use as a title for a new chat session:\n\n{selected_text}"
            messages = [{"role": "user", "content": prompt}]
            
            new_session_name = send_to_api(
                "New Discussion", 
                messages, 
                "gpt-3.5-turbo", 
                self.session_id, 
                widget=None, 
                save_message_to_db=False
            ).strip().strip('"')

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
        messages = get_messages(self.session_id)
        for i, (role, content) in enumerate(messages):
            plain_content = markdown_to_text(content)
            if role == 'user':
                self.chat_history.insert(tk.END, f"User:\n", ("user_tag", "bold"))
                self.chat_history.insert(tk.END, f"{plain_content}\n\n")
            elif role == 'assistant':
                self.chat_history.insert(tk.END, f"Assistant:\n", ("assistant_tag", "bold"))
                
                message_start_index = self.chat_history.index(tk.INSERT)
                self.chat_history.insert(tk.END, f"{plain_content}\n")
                message_end_index = self.chat_history.index(tk.INSERT)

                # Unique tags for each message body and its copy link
                message_body_tag = f"assistant_message_body_{i}"
                copy_link_tag = f"copy_link_for_{message_body_tag}"

                self.chat_history.tag_add(message_body_tag, message_start_index, message_end_index)
                
                self.chat_history.insert(tk.END, "Copy", ("copy_link", copy_link_tag))
                self.chat_history.insert(tk.END, "\n\n")

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

    def send_message(self, event=None):
        content = self.input_box.get("1.0", tk.END).strip()

        self.input_box.delete("1.0", tk.END)
        self.update_idletasks()

        if not content or not self.session_id:
            return "break"

        active_session_id = self.session_id
        save_message(self.session_id, "user", content)
        save_input_history(self.session_id, content)
        self.message_history = get_input_history(self.session_id)
        self.history_index = len(self.message_history)
        self.current_input_buffer = ""
        
        messages = get_messages(self.session_id)
        message_blocks = [{"role": role, "content": content} for role, content in messages]
        
        system_prompt = self.system_prompt_text.get("1.0", tk.END).strip()
        if system_prompt:
            message_blocks.insert(0, {"role": "system", "content": system_prompt})

        self.input_box.configure(state="disabled")
        self.chat_history.configure(state="normal")
        self.chat_history.insert(tk.END, f"User:\n{content}\n\n", ("user_tag", "bold"))
        self.chat_history.see(tk.END)
        self.chat_history.configure(state="disabled")
        self.update_idletasks()

        try:
            assistant_full_reply = send_to_api(self.session_name, message_blocks, self.model_var.get(), self.session_id, widget=self.chat_history, save_message_to_db=True)
            if assistant_full_reply: # Only summarize if there was a response
                self.summarize_and_rename_session()
        except requests.exceptions.RequestException as e:
            messagebox.showerror("Network Error", f"Could not connect to the server or API: {e}")
        except Exception as e:
            messagebox.showerror("Error", f"An unexpected error occurred: {e}")
        finally:
            self.input_box.configure(state="normal")
            self.input_box.focus_set()
            
            item_to_select = self.find_tree_item_by_id(active_session_id)
            if item_to_select:
                self.session_tree.selection_set(item_to_select)
                self.session_tree.focus(item_to_select)

            self.load_chat_history()

        return "break"

    def history_up(self, event=None):
        if not self.message_history:
            return "break"
            
        if self.history_index == len(self.message_history):
            self.current_input_buffer = self.input_box.get("1.0", tk.END)

        if self.history_index > 0:
            self.history_index -= 1
            self.input_box.delete("1.0", tk.END)
            self.input_box.insert("1.0", self.message_history[self.history_index])
        
        return "break"

    def history_down(self, event=None):
        if not self.message_history:
            return "break"

        if self.history_index < len(self.message_history) -1:
            self.history_index += 1
            self.input_box.delete("1.0", tk.END)
            self.input_box.insert("1.0", self.message_history[self.history_index])
        elif self.history_index == len(self.message_history) -1:
            self.history_index += 1
            self.input_box.delete("1.0", tk.END)
            self.input_box.insert("1.0", self.current_input_buffer)

        return "break"

    def increase_font_size(self, event=None):
        print("Increase font size called")
        new_size = self.chat_font_size.get() + 1
        if 8 <= new_size <= 72:
            self.chat_font_size.set(new_size)
            save_setting("chat_font_size", new_size)
            self.apply_font()

    def decrease_font_size(self, event=None):
        print("Decrease font size called")
        new_size = self.chat_font_size.get() - 1
        if 8 <= new_size <= 72:
            self.chat_font_size.set(new_size)
            save_setting("chat_font_size", new_size)
            self.apply_font()

    def find_dialog(self, event=None):
        self.search_frame.grid(row=1, column=0, sticky="ew", pady=2)
        self.input_container_frame.grid_remove()
        self.search_entry.focus_set()

    def find_next(self, event=None):
        self.chat_history.tag_remove('found', '1.0', tk.END)
        query = self.search_entry.get()
        if not query:
            return

        self.search_matches = []
        start_pos = '1.0'
        while True:
            start_pos = self.chat_history.search(query, start_pos, stopindex=tk.END, nocase=True)
            if not start_pos:
                break
            end_pos = f"{start_pos}+{len(query)}c"
            self.search_matches.append(start_pos)
            self.chat_history.tag_add('found', start_pos, end_pos)
            start_pos = end_pos
        
        self.chat_history.tag_config('found', background='yellow', foreground='black')

        if self.search_matches:
            self.current_match_index = (self.current_match_index + 1) % len(self.search_matches)
            self.chat_history.see(self.search_matches[self.current_match_index])
            self.chat_history.tag_remove('current_found', '1.0', tk.END)
            self.chat_history.tag_add('current_found', self.search_matches[self.current_match_index], f"{self.search_matches[self.current_match_index]}+{len(query)}c")
            self.chat_history.tag_config('current_found', background='orange', foreground='black')


    def find_prev(self, event=None):
        query = self.search_entry.get()
        if not query or not self.search_matches:
            return

        self.current_match_index = (self.current_match_index - 1) % len(self.search_matches)
        self.chat_history.see(self.search_matches[self.current_match_index])
        self.chat_history.tag_remove('current_found', '1.0', tk.END)
        self.chat_history.tag_add('current_found', self.search_matches[self.current_match_index], f"{self.search_matches[self.current_match_index]}+{len(query)}c")


    def hide_search(self, event=None):
        self.chat_history.tag_remove('found', '1.0', tk.END)
        self.chat_history.tag_remove('current_found', '1.0', tk.END)
        self.search_frame.grid_remove()
        self.input_container_frame.grid()
        self.input_box.focus_set()

if __name__ == "__main__":
    app = ChatApp()
    app.mainloop()