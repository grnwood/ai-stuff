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

load_dotenv()

API_URL = os.getenv("OPENAI_PROXY_URL", "http://localhost:3000/chat")
API_SECRET = os.getenv("API_SECRET_TOKEN", "my-secret-token")
DB_PATH = "chat_sessions.db"

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def get_available_models():
    try:
        models = client.models.list()
        available_models = sorted([model.id for model in models.data if "gpt" in model.id]) # Filter for GPT models and sort
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
                    model TEXT DEFAULT 'gpt-3.5-turbo'
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
    conn.commit()
    conn.close()

def get_sessions():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, model FROM sessions")
    sessions = c.fetchall()
    conn.close()
    return sessions

def create_session(name, model='gpt-3.5-turbo'):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO sessions (name, model) VALUES (?, ?)", (name, model))
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
def send_to_api(session_name, messages, model, chat_history_widget, current_session_id):
    ai_content = messages[-1]['content']
    prompt_content = ""
    system_content = None

    for msg in messages[:-1]:
        if msg['role'] == 'system':
            system_content = msg['content']
        else:
            prompt_content += f"{msg['role'].title()}: {msg['content']}\n\n"

    payload = {
        "model": model,
        "prompt": prompt_content.strip(),
        "ai": ai_content,
        "system": system_content,
        "session_id": session_name,
        "stream": True  # Enable streaming
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-secret": API_SECRET
    }

    assistant_full_reply = ""
    chat_history_widget.configure(state="normal")
    chat_history_widget.insert(tk.END, "Assistant:\n", ("assistant_tag")) # Start assistant message
    chat_history_widget.configure(state="disabled")
    chat_history_widget.see(tk.END)
    chat_history_widget.update_idletasks()

    with requests.post(API_URL, json=payload, headers=headers, stream=True) as resp:
        resp.raise_for_status()
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
                                chat_history_widget.configure(state="normal")
                                chat_history_widget.insert(tk.END, content_chunk)
                                chat_history_widget.configure(state="disabled")
                                chat_history_widget.see(tk.END)
                                chat_history_widget.update_idletasks()
                    except json.JSONDecodeError:
                        print(f"Skipping non-JSON line: {decoded_line}")
    
    # Save the complete assistant reply after streaming is done
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
class ChatApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Ask Proxy GUI")
        self.geometry("1000x600")
        self.configure(bg="#f0f0f0")

        init_db()
        self.session_id = None
        self.session_name = None
        self.message_history = []
        self.history_index = -1
        self.build_gui()
        self.load_sessions()

    def on_model_selected(self, event):
        if self.session_id:
            selected_model = self.model_var.get()
            update_session_model(self.session_id, selected_model)

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
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # --- Left Panel ---
        self.left_frame = ttk.Frame(self)
        self.left_frame.grid(row=0, column=0, sticky="ns")
        self.left_frame.columnconfigure(0, weight=1)
        self.left_frame.rowconfigure(2, weight=1) # Give weight to the row containing the session list

        # Model selection dropdown
        self.model_label = ttk.Label(self.left_frame, text="Select Model:")
        self.model_label.grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.model_var = tk.StringVar()
        self.model_dropdown = ttk.Combobox(self.left_frame, textvariable=self.model_var, state="readonly")
        self.model_dropdown.grid(row=1, column=0, sticky="ew", padx=5, pady=2)
        self.model_dropdown['values'] = get_available_models()
        self.model_dropdown.set("gpt-3.5-turbo") # Default value
        self.model_dropdown.bind('<<ComboboxSelected>>', self.on_model_selected) # Bind model selection event

        self.session_list = tk.Listbox(self.left_frame)
        self.session_list.grid(row=2, column=0, sticky="nsew")
        self.session_list.bind('<<ListboxSelect>>', self.select_session)
        self.session_list.bind('<Button-3>', self.show_session_context_menu)

        self.session_context_menu = tk.Menu(self.session_list, tearoff=0)
        self.session_context_menu.add_command(label="Rename", command=self.rename_session)
        self.session_context_menu.add_command(label="Delete", command=self.delete_session)

        self.new_button = ttk.Button(self.left_frame, text="+ New", command=self.new_session)
        self.new_button.grid(row=3, column=0, sticky="ew")

        self.export_button = ttk.Button(self.left_frame, text="Export Chat", command=self.export_chat)
        self.export_button.grid(row=4, column=0, sticky="ew")

        self.import_button = ttk.Button(self.left_frame, text="Import Chat", command=self.import_chat)
        self.import_button.grid(row=5, column=0, sticky="ew")

        # --- Main Chat Area ---
        self.main_frame = ttk.Frame(self)
        self.main_frame.grid(row=0, column=1, sticky="nsew")
        self.main_frame.rowconfigure(0, weight=1)
        self.main_frame.columnconfigure(0, weight=1)

        self.chat_history = ScrolledText(self.main_frame, state="disabled", wrap=tk.WORD, bg="white")
        self.chat_history.grid(row=0, column=0, sticky="nsew")

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

    def export_chat(self):
        if not self.session_id:
            messagebox.showinfo("Export Chat", "No session selected to export.")
            return

        messages = get_messages(self.session_id)
        if not messages:
            messagebox.showinfo("Export Chat", "Current session has no messages to export.")
            return

        # Get the current session's model
        current_session_info = None
        for _id, name, model in get_sessions():
            if _id == self.session_id:
                current_session_info = {"model": model, "messages": messages}
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

                if isinstance(imported_data, dict) and "model" in imported_data and "messages" in imported_data:
                    imported_model = imported_data["model"]
                    imported_messages = imported_data["messages"]
                elif isinstance(imported_data, list):
                    imported_messages = imported_data
                else:
                    raise ValueError("Invalid JSON format. Expected a list of messages or a dictionary with 'model' and 'messages'.")

                new_session_name = tk.simpledialog.askstring("Import Chat", "Enter a name for the new session:",
                                                              initialvalue=f"Imported Chat {len(get_sessions()) + 1}")
                if not new_session_name:
                    return

                session_id = create_session(new_session_name, imported_model) # Pass imported model
                for role, content in imported_messages:
                    save_message(session_id, role, content)

                self.load_sessions()
                self.session_list.selection_clear(0, tk.END)
                # Find the index of the newly created session and select it
                sessions = get_sessions()
                for i, (_id, name, model) in enumerate(sessions):
                    if _id == session_id:
                        self.session_list.selection_set(i)
                        self.session_list.event_generate('<<ListboxSelect>>')
                        break

                # Set the model dropdown after the session is loaded and selected
                if imported_model in get_available_models():
                    self.model_var.set(imported_model)
                else:
                    self.model_var.set("gpt-3.5-turbo") # Default if imported model is not available

                messagebox.showinfo("Import Chat", "Chat imported successfully!")

            except json.JSONDecodeError:
                messagebox.showerror("Import Error", "Invalid JSON file.")
            except ValueError as e:
                messagebox.showerror("Import Error", f"Error importing chat: {e}")
            except Exception as e:
                messagebox.showerror("Import Error", f"An unexpected error occurred: {e}")

    def load_sessions(self):
        self.session_list.delete(0, tk.END)
        sessions = get_sessions()
        for _id, name, model in sessions: # Added model to tuple unpacking
            self.session_list.insert(tk.END, name)

        if sessions:
            # Select the first session by default if any exist
            self.session_list.selection_set(0)
            self.session_list.event_generate('<<ListboxSelect>>')
        else:
            # Create a new session if no sessions exist
            self.new_session()

    def select_session(self, event):
        try:
            index = self.session_list.curselection()[0]
            _id, session_name, model = get_sessions()[index] # Get model along with id and name
            self.session_name = session_name
            self.session_id = _id
            self.model_var.set(model) # Set the dropdown to the session's model
            self.load_chat_history()
            self.message_history = get_input_history(self.session_id)
            self.history_index = len(self.message_history)
        except IndexError:
            return

    def get_session_id_by_name(self, name):
        # This function needs to be updated to fetch model as well if it's used to set model_var
        for _id, s_name, model in get_sessions(): # Added model to tuple unpacking
            if s_name == name:
                return _id
        return None

    def new_session(self):
        name = f"Session {len(get_sessions()) + 1}"
        selected_model = self.model_var.get() if self.model_var.get() else "gpt-3.5-turbo" # Use current selection or default
        session_id = create_session(name, selected_model)
        self.load_sessions()
        self.session_list.selection_clear(0, tk.END)
        # Find the index of the newly created session and select it
        sessions = get_sessions()
        for i, (_id, s_name, model) in enumerate(sessions): # Added model to tuple unpacking
            if _id == session_id:
                self.session_list.selection_set(i)
                self.session_list.event_generate('<<ListboxSelect>>')
                break
        self.chat_history.configure(state="normal")
        self.chat_history.delete("1.0", tk.END)
        self.chat_history.configure(state="disabled")

    def load_chat_history(self):
        self.chat_history.configure(state="normal")
        self.chat_history.delete("1.0", tk.END)
        messages = get_messages(self.session_id)
        for role, content in messages:
            self.chat_history.insert(tk.END, f"{role.title()}:\n{markdown_to_text(content)}\n\n")
        self.chat_history.see(tk.END)
        self.chat_history.configure(state="disabled")

    def send_message(self, event=None):
        content = self.input_box.get("1.0", tk.END).strip()

        # Clear input box immediately
        self.input_box.delete("1.0", tk.END)
        self.update_idletasks() # Update GUI immediately

        if not content or not self.session_id:
            return "break"

        save_message(self.session_id, "user", content)
        save_input_history(self.session_id, content) # Save to input history
        self.selection_clear()
        self.message_history = get_input_history(self.session_id) # Reload history for current session
        self.history_index = len(self.message_history) # Reset index to end after sending

        messages = get_messages(self.session_id)
        message_blocks = [{"role": role, "content": content} for role, content in messages]

        self.input_box.configure(state="disabled")
        self.chat_history.configure(state="normal")
        self.chat_history.insert(tk.END, "\nSending...\n", ("sending_tag"))
        self.chat_history.see(tk.END)
        self.chat_history.configure(state="disabled")
        self.update_idletasks() # Update GUI immediately  

        try:
            # Pass chat_history widget and session_id for real-time updates
            send_to_api(self.session_name, message_blocks, self.model_var.get(), self.chat_history, self.session_id)
            self.load_chat_history() # Reload history to ensure final state is saved and displayed
        except requests.exceptions.RequestException as e:
            messagebox.showerror("Network Error", f"Could not connect to the server or API: {e}")
            self.chat_history.configure(state="normal")
            self.chat_history.delete("end-2l", "end-1c") # Remove "Sending..."
            self.chat_history.configure(state="disabled")
        except Exception as e:
            messagebox.showerror("Error", f"An unexpected error occurred: {e}")
            self.chat_history.configure(state="normal")
            self.chat_history.delete("end-2l", "end-1c") # Remove "Sending..."
            self.chat_history.configure(state="disabled")
        finally:
            self.input_box.configure(state="normal")
            self.input_box.focus_set()

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