import tkinter as tk
from tkinter import font
import psutil
import json
import datetime
from pathlib import Path
import os
import subprocess
import sys

QUOTA_FILE = "quota.json"
MAX_DAILY_UPLOADS = 6

BASE_DIR = Path("videos_to_upload")
VALID_FOLDERS = ["Public", "Private", "Unlisted"]
VIDEO_EXTENSIONS = ('.mp4', '.mov', '.mkv', '.avi')

def is_uploader_running():
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline') or []
            # Check if it's a python process running our script
            if any('uploader.py' in cmd for cmd in cmdline) and 'python' in proc.info.get('name', '').lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False

def get_today_quota():
    today = datetime.date.today().isoformat()
    if os.path.exists(QUOTA_FILE):
        try:
            with open(QUOTA_FILE, "r") as f:
                data = json.load(f)
            if data.get("date") == today:
                return data.get("count", 0)
        except json.JSONDecodeError:
            pass
    return 0

def get_pending_queue_count():
    count = 0
    if not BASE_DIR.exists():
        return count
        
    for folder_name in VALID_FOLDERS:
        folder_path = BASE_DIR / folder_name
        if not folder_path.exists():
            continue
        for file_path in folder_path.iterdir():
            if file_path.is_file() and file_path.name.lower().endswith(VIDEO_EXTENSIONS):
                count += 1
    return count

def get_folder_count(folder_path):
    path = Path(folder_path)
    if not path.exists():
        return 0
    return sum(1 for f in path.iterdir() if f.is_file())

class DashboardApp:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Auto-Uploader Dashboard")
        self.root.geometry("400x360")
        self.root.configure(bg="#f4f4f9")
        self.root.resizable(False, False)
        
        # Fonts
        self.title_font = font.Font(family="Helvetica", size=18, weight="bold")
        self.label_font = font.Font(family="Helvetica", size=12)
        
        # Status Banner (explicit dark gray text to prevent visibility issues on macOS)
        self.status_label = tk.Label(self.root, text="Status: CHECKING...", font=self.title_font, bg="#f4f4f9", fg="#333333")
        self.status_label.pack(pady=(20, 10))
        
        # Metrics Frame
        self.metrics_frame = tk.Frame(self.root, bg="#f4f4f9")
        self.metrics_frame.pack(pady=10, padx=20, fill="x")
        
        # Metric Labels (explicit dark gray text)
        self.quota_var = tk.StringVar(value="Today's Uploads: 0 / 6")
        self.queue_var = tk.StringVar(value="Videos Pending in Queue: 0")
        self.archived_var = tk.StringVar(value="Total Successfully Archived: 0")
        self.failed_var = tk.StringVar(value="Total Failed: 0")
        
        self.create_metric_row(self.quota_var)
        self.create_metric_row(self.queue_var)
        self.create_metric_row(self.archived_var)
        self.create_metric_row(self.failed_var)
        
        # Control Buttons Frame
        self.btn_frame = tk.Frame(self.root, bg="#f4f4f9")
        self.btn_frame.pack(pady=15)
        
        # Refresh Button
        self.refresh_btn = tk.Button(self.btn_frame, text="Refresh Now", font=self.label_font, command=self.update_dashboard, bg="#dcdcdc", fg="#333333", relief="groove")
        self.refresh_btn.pack(side="left", padx=10)
        
        # Start Uploader Button
        self.start_btn = tk.Button(self.btn_frame, text="Start Uploader", font=self.label_font, command=self.start_uploader, bg="#dcdcdc", fg="#333333", relief="groove")
        self.start_btn.pack(side="left", padx=10)
        
        # Update Job ID for cancellation
        self.update_job = None
        
        # Start the loop
        self.update_dashboard()
        
    def create_metric_row(self, var):
        lbl = tk.Label(self.metrics_frame, textvariable=var, font=self.label_font, bg="#f4f4f9", fg="#333333", anchor="w")
        lbl.pack(fill="x", pady=5)
        
    def start_uploader(self):
        # Determine the python executable to use (defaults to current virtual environment python)
        python_exe = sys.executable
        script_path = Path(__file__).parent / "uploader.py"
        
        try:
            # Launch uploader as a background subprocess
            subprocess.Popen([python_exe, str(script_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # Instantly refresh status
            self.update_dashboard()
        except Exception as e:
            print(f"Error starting uploader: {e}")
            
    def update_dashboard(self):
        # Update Status and Start Button state
        if is_uploader_running():
            self.status_label.config(text="Status: RUNNING", fg="#2e7d32")  # High contrast green
            self.start_btn.config(state="disabled")
        else:
            self.status_label.config(text="Status: STOPPED", fg="#c62828")  # High contrast red
            self.start_btn.config(state="normal")
            
        # Update Quota
        quota = get_today_quota()
        self.quota_var.set(f"Today's Uploads: {quota} / {MAX_DAILY_UPLOADS}")
        
        # Update Queue
        queue = get_pending_queue_count()
        self.queue_var.set(f"Videos Pending in Queue: {queue}")
        
        # Update Archived
        archived = get_folder_count("uploaded_archive")
        self.archived_var.set(f"Total Successfully Archived: {archived}")
        
        # Update Failed
        failed = get_folder_count("failed_to_upload")
        self.failed_var.set(f"Total Failed: {failed}")
        
        # Auto-refresh every 5 seconds
        if self.update_job is not None:
            self.root.after_cancel(self.update_job)
        self.update_job = self.root.after(5000, self.update_dashboard)

if __name__ == "__main__":
    root = tk.Tk()
    app = DashboardApp(root)
    root.mainloop()

