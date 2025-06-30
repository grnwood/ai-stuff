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
from openai import OpenAI
from tkinter import font

load_dotenv()

API_URL = os.getenv("OPENAI_PROXY_URL", "http://localhost:3000")
API_SECRET = os.getenv("API_SECRET_TOKEN", "my-secret-token")
DB_PATH = "chat_sessions.db"

def get_available_models():
    try:
        response = requests.get(f"{API_URL}/v1/models", headers={"x-api-secret": API_SECRET})
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
                    name TEXT UNIQUE NOT NULL,
                    model TEXT DEFAULT 'gpt-3.5-turbo',
                    system_prompt TEXT
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
    c.execute("SELECT id, name, model, system_prompt FROM sessions")
    sessions = c.fetchall()
    conn.close()
    return sessions

def create_session(name, model='gpt-3.5-turbo', system_prompt=''):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO sessions (name, model, system_prompt) VALUES (?, ?, ?)", (name, model, system_prompt))
    conn.commit()
    session_id = c.lastrowid
    conn.close()
    return session_id

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

def send_to_api(session_name, messages, model, chat_history_widget, current_session_id, widget=None, save_message_to_db=True):
    if widget is None:
        widget = chat_history_widget
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

# --- GUI ---
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
        x, y, _, _ = self.widget.bbox("insert")
        x = x + self.widget.winfo_rootx() + 25
        y = y + self.widget.winfo_rooty() + 20
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
        self.title("Ask Proxy GUI")
        self.geometry("1000x600")

        init_db()
        self.session_id = None
        self.session_name = None
        self.message_history = []
        self.history_index = -1
        
        self.theme = tk.StringVar(value=get_setting("theme", "light"))
        self.chat_font = tk.StringVar(value=get_setting("chat_font", "TkDefaultFont"))

        self.build_gui()
        self.apply_theme()
        self.apply_font()
        self.load_sessions()

    def on_model_selected(self, event):
        if self.session_id:
            selected_model = self.model_var.get()
            update_session_model(self.session_id, selected_model)

    def on_session_list_motion(self, event):
        index = self.session_list.index(f"@{event.x},{event.y}")
        if index != self.last_hovered_index:
            self.last_hovered_index = index
            self.session_tooltip.hidetip()
            try:
                session_name = self.session_list.get(index)
                self.session_tooltip.showtip(session_name)
            except tk.TclError:
                pass # Ignore errors when mouse is not over an item
    
    def show_session_context_menu(self, event):
        try:
            self.session_list.selection_clear(0, tk.END)
            self.session_list.selection_set(self.session_list.nearest(event.y))
            self.session_context_menu.post(event.x_root, event.y_root)
        finally:
            self.session_context_menu.grab_release()

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
        try:
            index = self.session_list.curselection()[0]
            session_name = self.session_list.get(index)
            session_id = self.get_session_id_by_name(session_name)

            if messagebox.askyesno("Delete Session", f"Are you sure you want to delete session '{session_name}' and all its messages?"):
                delete_session_and_messages(session_id)
                self.load_sessions()
                if self.session_id == session_id:
                    self.session_id = None
                    self.session_name = None
                    self.chat_history.configure(state="normal")
                    self.chat_history.delete("1.0", tk.END)
                    self.chat_history.configure(state="disabled")
        except IndexError:
            pass

    def build_gui(self):
        # Main PanedWindow (Left and Right Panels)
        self.main_paned_window = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.main_paned_window.pack(fill=tk.BOTH, expand=True)

        # Left PanedWindow (Session List and Main Chat Area)
        self.left_paned_window = ttk.PanedWindow(self.main_paned_window, orient=tk.HORIZONTAL)
        self.main_paned_window.add(self.left_paned_window, weight=1)

        # --- Left Panel (Session List) ---
        self.left_frame = ttk.Frame(self.left_paned_window, width=200)
        self.left_paned_window.add(self.left_frame, weight=1)
        self.left_frame.columnconfigure(0, weight=1)
        self.left_frame.rowconfigure(2, weight=1)

        self.model_label = ttk.Label(self.left_frame, text="Select Model:")
        self.model_label.grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.model_var = tk.StringVar()
        self.model_dropdown = ttk.Combobox(self.left_frame, textvariable=self.model_var, state="readonly")
        self.model_dropdown.grid(row=1, column=0, sticky="ew", padx=5, pady=2)
        self.model_dropdown['values'] = get_available_models()
        self.model_dropdown.set("gpt-3.5-turbo")
        self.model_dropdown.bind('<<ComboboxSelected>>', self.on_model_selected)

        self.session_list = tk.Listbox(self.left_frame)
        self.session_list.grid(row=2, column=0, sticky="nsew")
        self.session_list.bind('<<ListboxSelect>>', self.select_session)
        self.session_list.bind('<Button-3>', self.show_session_context_menu)
        self.session_list.bind('<Motion>', self.on_session_list_motion)

        self.session_tooltip = ToolTip(self.session_list)
        self.last_hovered_index = -1

        self.session_context_menu = tk.Menu(self.session_list, tearoff=0)
        self.session_context_menu.add_command(label="Rename", command=self.rename_session)
        self.session_context_menu.add_command(label="Delete", command=self.delete_session)

        self.new_button = ttk.Button(self.left_frame, text="+ New", command=self.new_session)
        self.new_button.grid(row=3, column=0, sticky="ew")

        self.export_button = ttk.Button(self.left_frame, text="Export Chat", command=self.export_chat)
        self.export_button.grid(row=4, column=0, sticky="ew")

        self.import_button = ttk.Button(self.left_frame, text="Import Chat", command=self.import_chat)
        self.import_button.grid(row=5, column=0, sticky="ew")

        self.settings_button = ttk.Button(self.left_frame, text="Settings", command=self.open_settings)
        self.settings_button.grid(row=6, column=0, sticky="ew")

        # --- Main Chat Area ---
        self.main_frame = ttk.Frame(self.left_paned_window)
        self.left_paned_window.add(self.main_frame, weight=4)
        self.main_frame.rowconfigure(0, weight=1)
        self.main_frame.columnconfigure(0, weight=1)

        self.chat_history = ScrolledText(self.main_frame, wrap=tk.WORD)
        self.chat_history.grid(row=0, column=0, sticky="nsew")
        self.chat_history.bind("<KeyPress>", lambda e: "break")

        self.chat_history.tag_config("user_tag", foreground="#0078D7")
        self.chat_history.tag_config("assistant_tag", foreground="#008000")
        self.chat_history.tag_config("copy_link", foreground="blue", underline=True)
        self.chat_history.tag_bind("copy_link", "<Button-1>", self.copy_message_from_link)
        self.chat_history.tag_bind("copy_link", "<Enter>", lambda e: self.chat_history.config(cursor="hand2"))
        self.chat_history.tag_bind("copy_link", "<Leave>", lambda e: self.chat_history.config(cursor=""))

        self.chat_history_menu = tk.Menu(self.chat_history, tearoff=0)
        self.chat_history_menu.add_command(label="Copy", command=self.copy_chat_selection)
        self.chat_history.bind("<Button-3>", self.show_chat_context_menu)

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
        self.right_frame.rowconfigure(1, weight=1)
        
        self.system_prompt_label = ttk.Label(self.right_frame, text="System Prompt:")
        self.system_prompt_label.grid(row=0, column=0, sticky="w", padx=5, pady=5)
        
        self.system_prompt_text = ScrolledText(self.right_frame, wrap=tk.WORD, height=10)
        self.system_prompt_text.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        self.system_prompt_text.bind("<<Modified>>", self.on_system_prompt_modified)

        # --- Toggle Button for Right Panel ---
        self.toggle_right_panel_button = ttk.Button(self, text="<", command=self.toggle_right_panel)
        self.toggle_right_panel_button.place(relx=1.0, rely=0.5, anchor="e")

        # --- Status Bar ---
        self.status_bar = ttk.Label(self, text="", anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

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
        if theme == "dark":
            self.configure(bg="#2b2b2b")
            # Left panel
            self.left_frame.configure(style="Dark.TFrame")
            self.model_label.configure(style="Dark.TLabel")
            self.session_list.configure(bg="#3c3f41", fg="white", selectbackground="#4f5254", selectforeground="white")
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
            s = ttk.Style()
            s.configure("Dark.TFrame", background="#2b2b2b")
            s.configure("Dark.TLabel", background="#2b2b2b", foreground="white")
            s.configure("Dark.TButton", background="#4f5254", foreground="white")
            s.map("Dark.TButton", background=[('active', '#6f7274')])
        else: # Light mode
            self.configure(bg="#f0f0f0")
            # Left panel
            self.left_frame.configure(style="TFrame")
            self.model_label.configure(style="TLabel")
            self.session_list.configure(bg="white", fg="black", selectbackground="#0078d7", selectforeground="white")
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

    def apply_font(self):
        font_name = self.chat_font.get()
        try:
            custom_font = font.Font(family=font_name, size=10)
            self.chat_history.configure(font=custom_font)
            self.input_box.configure(font=custom_font)
        except tk.TclError:
            print(f"Font '{font_name}' not found, using default.")
            default_font = font.Font(family="TkDefaultFont", size=10)
            self.chat_history.configure(font=default_font)
            self.input_box.configure(font=default_font)

    def open_settings(self):
        settings_win = tk.Toplevel(self)
        settings_win.title("Settings")
        settings_win.geometry("300x300")
        
        # Theme settings
        ttk.Label(settings_win, text="Theme:").pack(pady=5)
        
        def on_theme_change():
            save_setting("theme", self.theme.get())
            self.apply_theme()

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

    def export_chat(self):
        if not self.session_id:
            messagebox.showinfo("Export Chat", "No session selected to export.")
            return

        messages = get_messages(self.session_id)
        
        # Get the current session's details
        current_session_info = None
        for _id, name, model, system_prompt in get_sessions():
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

                session_id = create_session(new_session_name, imported_model, imported_system_prompt)
                for role, content in imported_messages:
                    save_message(session_id, role, content)

                self.load_sessions()
                self.session_list.selection_clear(0, tk.END)
                
                sessions = get_sessions()
                for i, (_id, name, model, system_prompt) in enumerate(sessions):
                    if _id == session_id:
                        self.session_list.selection_set(i)
                        self.session_list.event_generate('<<ListboxSelect>>')
                        break

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

    def load_sessions(self, set_selection=True):
        self.session_list.delete(0, tk.END)
        sessions = get_sessions()
        for _id, name, model, empty in sessions: # Added model to tuple unpacking
            self.session_list.insert(tk.END, name)

        if sessions:
            if set_selection:
                # Select the first session by default if any exist
                self.session_list.selection_set(0)
                self.session_list.event_generate('<<ListboxSelect>>')
        else:
            # Create a new session if no sessions exist
            self.new_session()

    def select_session(self, event):
        try:
            index = self.session_list.curselection()[0]
            _id, session_name, model, system_prompt = get_sessions()[index]
            self.session_name = session_name
            self.session_id = _id
            self.title(f"Ask Proxy GUI - {self.session_name}")
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
        except IndexError:
            self.title("Ask Proxy GUI")
            return

    def get_session_id_by_name(self, name):
        # This function needs to be updated to fetch model as well if it's used to set model_var
        for _id, s_name, model, empty in get_sessions(): # Added model to tuple unpacking
            if s_name == name:
                return _id
        return None

    def new_session(self):
        name = f"Session {len(get_sessions()) + 1}"
        default_model = get_setting("default_model", "gpt-3.5-turbo")
        session_id = create_session(name, default_model)
        self.load_sessions()
        self.session_list.selection_clear(0, tk.END)
        # Find the index of the newly created session and select it
        sessions = get_sessions()
        for i, (_id, s_name, model, system_prompt) in enumerate(sessions):
            if _id == session_id:
                self.session_list.selection_set(i)
                self.session_list.event_generate('<<ListboxSelect>>')
                break
        self.chat_history.delete("1.0", tk.END)

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
        # Show context menu only if there is a selection
        if self.chat_history.tag_ranges("sel"):
            self.chat_history_menu.post(event.x_root, event.y_root)

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

        prompt = f"current chat session name is '{self.session_name}'. Summarize this session in 5 words or less only change it when a significant shift occurs:\n\n{conversation}"

        try:
            messages_for_summary = [
                {"role": "system", "content": "You are a helpful assistant that summarizes chat sessions."},
                {"role": "user", "content": prompt}
            ]
            
            # Call send_to_api without a widget to get the response directly
            new_name = send_to_api(
                self.session_name, 
                messages_for_summary, 
                "gpt-3.5-turbo", 
                self.chat_history, 
                self.session_id, 
                widget=None,
                save_message_to_db=False
            ).strip()

            if new_name and new_name != self.session_name and len(new_name.split()) <= 5:
                current_selection_index = self.session_list.curselection()
                if not current_selection_index:
                    return 

                update_session_name(self.session_id, new_name)
                self.session_name = new_name
                
                # Update the name in the listbox directly
                self.session_list.delete(current_selection_index[0])
                self.session_list.insert(current_selection_index[0], new_name)
                self.session_list.selection_set(current_selection_index[0])
                self.title(f"Ask Proxy GUI - {self.session_name}")


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
            assistant_full_reply = send_to_api(self.session_name, message_blocks, self.model_var.get(), self.chat_history, self.session_id, widget=self.chat_history, save_message_to_db=True)
            if assistant_full_reply: # Only summarize if there was a response
                self.summarize_and_rename_session()
        except requests.exceptions.RequestException as e:
            messagebox.showerror("Network Error", f"Could not connect to the server or API: {e}")
        except Exception as e:
            messagebox.showerror("Error", f"An unexpected error occurred: {e}")
        finally:
            self.input_box.configure(state="normal")
            self.input_box.focus_set()
            
            sessions = get_sessions()
            for i, (_id, name, model, system_prompt) in enumerate(sessions):
                if _id == active_session_id:
                    self.session_list.selection_set(i)
                    self.session_list.activate(i)
                    self.session_list.see(i)
                    break
            self.load_chat_history()

        return "break"

    def history_up(self, event=None):
        if self.message_history:
            if self.history_index > 0:
                self.history_index -= 1
            self.input_box.delete("1.0", tk.END)
            self.input_box.insert("1.0", self.message_history[self.history_index])
        return "break"

    def history_down(self, event=None):
        if self.message_history:
            if self.history_index < len(self.message_history) - 1:
                self.history_index += 1
                self.input_box.delete("1.0", tk.END)
                self.input_box.insert("1.0", self.message_history[self.history_index])
            elif self.history_index == len(self.message_history) - 1: # If at the last item, clear input
                self.history_index = len(self.message_history)
                self.input_box.delete("1.0", tk.END)
        return "break"

if __name__ == "__main__":
    app = ChatApp()
    app.mainloop()