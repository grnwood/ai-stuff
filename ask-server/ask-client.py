import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
import requests
import os
import json
import sqlite3
from markdown import markdown
from html.parser import HTMLParser
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("OPENAI_PROXY_URL", "http://localhost:3000/chat")
API_SECRET = os.getenv("API_SECRET_TOKEN", "my-secret-token")
DB_PATH = "chat_sessions.db"

# --- Database ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
                    session_id INTEGER,
                    role TEXT,
                    content TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                )''')
    conn.commit()
    conn.close()

def get_sessions():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name FROM sessions")
    sessions = c.fetchall()
    conn.close()
    return sessions

def create_session(name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO sessions (name) VALUES (?)", (name,))
    conn.commit()
    session_id = c.lastrowid
    conn.close()
    return session_id

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

# --- API ---
def send_to_api(session_name, messages):
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": messages,
        "session_id": session_name,
        "stream": False
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-secret": API_SECRET
    }
    resp = requests.post(API_URL, json=payload, headers=headers)
    resp.raise_for_status()
    return resp.json()['choices'][0]['message']['content']

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
class ChatApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Ask Proxy GUI")
        self.geometry("1000x600")
        self.configure(bg="#f0f0f0")

        init_db()
        self.session_id = None
        self.session_name = None
        self.build_gui()
        self.load_sessions()

    def build_gui(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # --- Left Panel ---
        self.left_frame = ttk.Frame(self)
        self.left_frame.grid(row=0, column=0, sticky="ns")
        self.left_frame.columnconfigure(0, weight=1)

        self.session_list = tk.Listbox(self.left_frame)
        self.session_list.grid(row=0, column=0, sticky="nsew")
        self.session_list.bind('<<ListboxSelect>>', self.select_session)

        self.new_button = ttk.Button(self.left_frame, text="+ New", command=self.new_session)
        self.new_button.grid(row=1, column=0, sticky="ew")

        # --- Main Chat Area ---
        self.main_frame = ttk.Frame(self)
        self.main_frame.grid(row=0, column=1, sticky="nsew")
        self.main_frame.rowconfigure(0, weight=1)
        self.main_frame.columnconfigure(0, weight=1)

        self.chat_history = ScrolledText(self.main_frame, state="disabled", wrap=tk.WORD, bg="white")
        self.chat_history.grid(row=0, column=0, sticky="nsew")

        self.input_box = tk.Text(self.main_frame, height=5, wrap=tk.WORD)
        self.input_box.grid(row=1, column=0, sticky="ew")
        self.input_box.bind("<Control-Return>", self.send_message)

    def load_sessions(self):
        self.session_list.delete(0, tk.END)
        for _id, name in get_sessions():
            self.session_list.insert(tk.END, name)

    def select_session(self, event):
        try:
            index = self.session_list.curselection()[0]
            session_name = self.session_list.get(index)
            self.session_name = session_name
            self.session_id = self.get_session_id_by_name(session_name)
            self.load_chat_history()
        except IndexError:
            return

    def get_session_id_by_name(self, name):
        for _id, s_name in get_sessions():
            if s_name == name:
                return _id
        return None

    def new_session(self):
        name = f"Session {len(get_sessions()) + 1}"
        session_id = create_session(name)
        self.load_sessions()
        self.session_list.selection_clear(0, tk.END)
        self.session_list.selection_set(tk.END)
        self.session_name = name
        self.session_id = session_id
        self.chat_history.configure(state="normal")
        self.chat_history.delete("1.0", tk.END)
        self.chat_history.configure(state="disabled")

    def load_chat_history(self):
        self.chat_history.configure(state="normal")
        self.chat_history.delete("1.0", tk.END)
        messages = get_messages(self.session_id)
        for role, content in messages:
            self.chat_history.insert(tk.END, f"{role.title()}:\n{markdown_to_text(content)}\n\n")
        self.chat_history.configure(state="disabled")

    def send_message(self, event=None):
        content = self.input_box.get("1.0", tk.END).strip()
        if not content or not self.session_id:
            return "break"

        save_message(self.session_id, "user", content)
        messages = get_messages(self.session_id)
        message_blocks = [{"role": role, "content": content} for role, content in messages]

        try:
            assistant_reply = send_to_api(self.session_name, message_blocks)
            save_message(self.session_id, "assistant", assistant_reply)
            self.load_chat_history()
            self.input_box.delete("1.0", tk.END)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to get response: {e}")

        return "break"

if __name__ == "__main__":
    app = ChatApp()
    app.mainloop()

