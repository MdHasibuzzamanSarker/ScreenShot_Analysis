import os
import json
import datetime
import threading
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import google.generativeai as genai
from PIL import Image, ImageTk

# --- CONFIGURATION ---
HISTORY_FILE = "chat_history.json"
THUMBNAIL_SIZE = (120, 120)
# This default is used only if auto-detection fails
FALLBACK_MODEL = "gemini-1.5-flash-latest" 

# --- BACKEND LOGIC ---
class GeminiClient:
    def __init__(self, api_key):
        if not api_key:
            raise ValueError("No API Key provided.")
        genai.configure(api_key=api_key)
        
        # --- DYNAMIC MODEL SELECTION ---
        # This ensures we always get the newest "Flash" model available to your API key
        self.model_name = self.find_latest_flash_model()
        print(f"✅ Using Model: {self.model_name}")
        
        self.model = genai.GenerativeModel(self.model_name)
        self.chat = None

    def find_latest_flash_model(self):
        """
        Queries the API to find the latest available 'flash' model.
        Returns the specific model name to ensure future compatibility.
        """
        try:
            # List all models available to the user
            models = list(genai.list_models())
            
            # Filter for models that support content generation and contain "flash"
            flash_models = [
                m.name for m in models 
                if 'generateContent' in m.supported_generation_methods 
                and 'flash' in m.name.lower()
            ]
            
            if not flash_models:
                return FALLBACK_MODEL

            # Sort to try and get the "latest" or highest version number
            # Usually strict alphabetical sort works well for version numbers (1.5 < 2.0)
            # We prefer 'latest' aliases if they exist, otherwise the newest version.
            flash_models.sort(reverse=True)
            return flash_models[0]
            
        except Exception as e:
            print(f"⚠️ Could not auto-detect model: {e}")
            return FALLBACK_MODEL

    def start_new_session(self, images, prompt_text="Analyze these images."):
        self.chat = self.model.start_chat(history=[])
        content = [prompt_text] + images
        return self.chat.send_message(content)

    def send_message(self, text):
        if not self.chat:
            raise RuntimeError("Chat session not initialized.")
        return self.chat.send_message(text)

    def resume_session(self, history_data, images):
        self.chat = self.model.start_chat(history=[])
        if images:
            self.chat.send_message(["System: Context restoration.", *images])

class HistoryManager:
    @staticmethod
    def load():
        if not os.path.exists(HISTORY_FILE):
            return {}
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    @staticmethod
    def save(chat_id, title, image_paths, history_log):
        data = HistoryManager.load()
        entry = {
            "title": title,
            "images": image_paths,
            "messages": history_log,
            "updated_at": datetime.datetime.now().isoformat()
        }
        data[chat_id] = entry
        with open(HISTORY_FILE, "w") as f:
            json.dump(data, f, indent=4)

    @staticmethod
    def delete_entry(chat_id):
        data = HistoryManager.load()
        if chat_id in data:
            del data[chat_id]
            with open(HISTORY_FILE, "w") as f:
                json.dump(data, f, indent=4)

    @staticmethod
    def clear_all():
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "w") as f:
                json.dump({}, f)

# --- FRONTEND UI ---
class App:
    def __init__(self, root):
        self.root = root
        root.title("Gemini Auto-Flash Analyst")
        root.geometry("1100x750")

        # Load API Key
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError: pass
        
        self.api_key = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY"))
        self.client = None
        self.msg_queue = queue.Queue()
        
        # State
        self.current_chat_id = None
        self.current_image_paths = []
        self.pil_images = []
        self.tk_images = [] 
        self.chat_log_data = []

        self.setup_ui()
        self.check_queue() 

        # Initialize Client in a thread to not block UI startup (API check takes ~1s)
        if self.api_key:
            threading.Thread(target=self.init_client_bg, daemon=True).start()
        else:
            self.log_system("⚠️ Critical: No API Key found in environment.")

    def init_client_bg(self):
        try:
            self.client = GeminiClient(self.api_key)
            # Notify UI which model was selected
            model_name = self.client.model_name.replace('models/', '')
            self.msg_queue.put(("status", f"Ready (Model: {model_name})"))
        except Exception as e:
            self.msg_queue.put(("error", f"Startup Error: {e}"))

    def setup_ui(self):
        paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Sidebar
        sidebar = tk.Frame(paned, width=280, bg="#f5f5f5")
        paned.add(sidebar)

        notebook = ttk.Notebook(sidebar)
        notebook.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        
        # Tab 1: New
        tab_new = tk.Frame(notebook)
        notebook.add(tab_new, text="New Chat")
        
        tk.Button(tab_new, text="📂 Select Images", command=self.select_images, height=2, bg="#e3f2fd").pack(fill=tk.X, padx=5, pady=5)
        self.file_list = tk.Listbox(tab_new, selectmode=tk.MULTIPLE, height=10)
        self.file_list.pack(fill=tk.BOTH, expand=True, padx=5)
        self.btn_start = tk.Button(tab_new, text="🚀 Analyze", command=self.start_analysis_thread, bg="#c8e6c9", state=tk.DISABLED)
        self.btn_start.pack(fill=tk.X, padx=5, pady=10)

        # Tab 2: History
        tab_hist = tk.Frame(notebook)
        notebook.add(tab_hist, text="History")
        
        hist_controls = tk.Frame(tab_hist)
        hist_controls.pack(fill=tk.X, padx=2, pady=2)
        tk.Button(hist_controls, text="Delete Selected", command=self.delete_selected_history, bg="#ffcdd2", font=("Segoe UI", 8)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=1)
        tk.Button(hist_controls, text="Clear All", command=self.clear_all_history, bg="#ef5350", fg="white", font=("Segoe UI", 8)).pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=1)
        tk.Button(tab_hist, text="🔄 Refresh List", command=self.load_history_ui).pack(fill=tk.X, padx=2, pady=(2,5))
        
        self.hist_list = tk.Listbox(tab_hist)
        self.hist_list.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.hist_list.bind('<<ListboxSelect>>', self.load_history_item)

        # Main Content
        main_frame = tk.Frame(paned, bg="white")
        paned.add(main_frame)

        self.preview_frame = tk.Frame(main_frame, height=140, bg="#eeeeee")
        self.preview_frame.pack(fill=tk.X, padx=5, pady=5)
        self.preview_label = tk.Label(self.preview_frame, text="No images selected", bg="#eeeeee", fg="#666")
        self.preview_label.pack(pady=50)

        self.chat_display = scrolledtext.ScrolledText(main_frame, state=tk.DISABLED, wrap=tk.WORD, font=("Segoe UI", 10))
        self.chat_display.pack(fill=tk.BOTH, expand=True, padx=10)
        self.setup_tags()

        input_frame = tk.Frame(main_frame, bg="white")
        input_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.entry_var = tk.StringVar()
        entry = tk.Entry(input_frame, textvariable=self.entry_var, font=("Segoe UI", 11))
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        entry.bind("<Return>", self.send_message_thread)
        
        self.btn_send = tk.Button(input_frame, text="Send", command=self.send_message_thread, width=10)
        self.btn_send.pack(side=tk.RIGHT, padx=(5,0))

        self.status_bar = tk.Label(main_frame, text="Initializing...", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.load_history_ui()

    def setup_tags(self):
        self.chat_display.tag_config('user', foreground='#1a73e8', font=("Segoe UI", 10, "bold"), spacing3=5)
        self.chat_display.tag_config('model', foreground='#202124', spacing3=15)
        self.chat_display.tag_config('system', foreground='#5f6368', font=("Segoe UI", 9, "italic"), spacing3=5)
        self.chat_display.tag_config('error', foreground='#d93025', font=("Segoe UI", 9, "bold"))

    def check_queue(self):
        try:
            while True:
                task_type, data = self.msg_queue.get_nowait()
                if task_type == "ui_append": self.append_text(*data)
                elif task_type == "status": self.status_bar.config(text=data)
                elif task_type == "enable_controls": self.set_controls(True)
                elif task_type == "error":
                    self.append_text("error", f"Error: {data}")
                    self.set_controls(True)
                    self.status_bar.config(text="Error occurred")
                self.msg_queue.task_done()
        except queue.Empty: pass
        finally: self.root.after(100, self.check_queue)

    def set_controls(self, state):
        s = tk.NORMAL if state else tk.DISABLED
        self.btn_send.config(state=s)
        self.btn_start.config(state=s)

    def select_images(self):
        paths = filedialog.askopenfilenames(filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.webp")])
        if paths:
            self.current_image_paths = list(paths)
            self.file_list.delete(0, tk.END)
            self.pil_images = []
            self.tk_images = []
            for p in paths: self.file_list.insert(tk.END, os.path.basename(p))
            for widget in self.preview_frame.winfo_children(): widget.destroy()
            for p in paths:
                try:
                    img = Image.open(p)
                    self.pil_images.append(img)
                    thumb = img.copy()
                    thumb.thumbnail(THUMBNAIL_SIZE)
                    photo = ImageTk.PhotoImage(thumb)
                    self.tk_images.append(photo)
                    tk.Label(self.preview_frame, image=photo, bd=1).pack(side=tk.LEFT, padx=5, pady=5)
                except Exception as e: print(f"Load error: {e}")
            self.btn_start.config(state=tk.NORMAL)

    def start_analysis_thread(self):
        if not self.pil_images: return
        self.set_controls(False)
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.delete(1.0, tk.END)
        self.chat_display.config(state=tk.DISABLED)
        self.chat_log_data = []
        self.current_chat_id = datetime.datetime.now().isoformat()
        self.status_bar.config(text="Analyzing images...")
        self.msg_queue.put(("ui_append", ("system", f"Uploading {len(self.pil_images)} images...")))
        threading.Thread(target=self._bg_start_analysis, daemon=True).start()

    def _bg_start_analysis(self):
        try:
            if not self.client: raise ValueError("Client not ready")
            response = self.client.start_new_session(self.pil_images)
            self.msg_queue.put(("ui_append", ("model", response.text)))
            self._save_msg("model", response.text)
            self.msg_queue.put(("status", "Chat Active"))
            self.msg_queue.put(("enable_controls", True))
        except Exception as e: self.msg_queue.put(("error", str(e)))

    def send_message_thread(self, event=None):
        msg = self.entry_var.get().strip()
        if not msg: return
        self.entry_var.set("")
        self.append_text("user", f"You: {msg}")
        self._save_msg("user", msg)
        self.set_controls(False)
        self.status_bar.config(text="Thinking...")
        threading.Thread(target=self._bg_send_message, args=(msg,), daemon=True).start()

    def _bg_send_message(self, text):
        try:
            response = self.client.send_message(text)
            self.msg_queue.put(("ui_append", ("model", response.text)))
            self._save_msg("model", response.text)
            self.msg_queue.put(("status", "Ready"))
            self.msg_queue.put(("enable_controls", True))
        except Exception as e: self.msg_queue.put(("error", str(e)))

    def _save_msg(self, role, text):
        self.chat_log_data.append({"role": role, "text": text})
        title = "Chat"
        for m in self.chat_log_data:
            if m['role'] == 'model':
                title = m['text'][:30] + "..."
                break
        HistoryManager.save(self.current_chat_id, title, self.current_image_paths, self.chat_log_data)
        self.root.after(0, self.load_history_ui)

    def append_text(self, tag, text):
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.insert(tk.END, text + "\n\n", tag)
        self.chat_display.see(tk.END)
        self.chat_display.config(state=tk.DISABLED)

    def log_system(self, text): self.append_text("system", text)

    def load_history_ui(self):
        sel = self.hist_list.curselection()
        self.hist_list.delete(0, tk.END)
        data = HistoryManager.load()
        for date_key in sorted(data.keys(), reverse=True):
            display = f"{date_key[:16].replace('T', ' ')} | {data[date_key]['title']}"
            self.hist_list.insert(tk.END, display)
        if sel and sel[0] < self.hist_list.size(): self.hist_list.selection_set(sel)

    def delete_selected_history(self):
        sel = self.hist_list.curselection()
        if not sel: return
        data = HistoryManager.load()
        keys = sorted(data.keys(), reverse=True)
        if sel[0] < len(keys):
            chat_id = keys[sel[0]]
            HistoryManager.delete_entry(chat_id)
            self.load_history_ui()
            if self.current_chat_id == chat_id:
                self.chat_display.config(state=tk.NORMAL)
                self.chat_display.delete(1.0, tk.END)
                self.chat_display.config(state=tk.DISABLED)
                self.status_bar.config(text="Deleted")

    def clear_all_history(self):
        if messagebox.askyesno("Confirm", "Delete ALL history?"):
            HistoryManager.clear_all()
            self.load_history_ui()
            self.chat_display.config(state=tk.NORMAL)
            self.chat_display.delete(1.0, tk.END)
            self.chat_display.config(state=tk.DISABLED)

    def load_history_item(self, event):
        sel = self.hist_list.curselection()
        if not sel: return
        data = HistoryManager.load()
        keys = sorted(data.keys(), reverse=True)
        if sel[0] >= len(keys): return
        chat_data = data[keys[sel[0]]]
        
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.delete(1.0, tk.END)
        self.chat_log_data = chat_data['messages']
        self.current_chat_id = keys[sel[0]]
        for msg in chat_data['messages']:
            tag = "user" if msg['role'] == "user" else "model"
            prefix = "You: " if tag == "user" else ""
            self.chat_display.insert(tk.END, f"{prefix}{msg['text']}\n\n", tag)
        self.chat_display.config(state=tk.DISABLED)
        
        self.current_image_paths = chat_data['images']
        self.pil_images = []
        for widget in self.preview_frame.winfo_children(): widget.destroy()
        valid_images = []
        for p in self.current_image_paths:
            if os.path.exists(p):
                try:
                    img = Image.open(p)
                    valid_images.append(img)
                    thumb = img.copy()
                    thumb.thumbnail(THUMBNAIL_SIZE)
                    photo = ImageTk.PhotoImage(thumb)
                    self.tk_images.append(photo)
                    tk.Label(self.preview_frame, image=photo, bd=1).pack(side=tk.LEFT, padx=2)
                except: pass
        self.pil_images = valid_images
        if self.client: threading.Thread(target=self.client.resume_session, args=(None, valid_images), daemon=True).start()
        self.status_bar.config(text="History Loaded")

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()