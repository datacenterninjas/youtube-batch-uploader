import tkinter as tk
from tkinter import font
import psutil
import json
import datetime
from pathlib import Path
import os

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
        self.root.geometry("400x350")
        self.root.configure(bg="#f4f4f9")
        self.root.resizable(False, False)
        
        # Fonts
        self.title_font = font.Font(family="Helvetica", size=18, weight="bold")
        self.label_font = font.Font(family="Helvetica", size=12)
        
        # Status Banner
        self.status_label = tk.Label(self.root, text="Status: CHECKING...", font=self.title_font, bg="#f4f4f9")
        self.status_label.pack(pady=(20, 10))
        
        # Metrics Frame
        self.metrics_frame = tk.Frame(self.root, bg="#f4f4f9")
        self.metrics_frame.pack(pady=10, padx=20, fill="x")
        
        # Metric Labels
        self.quota_var = tk.StringVar(value="Today's Uploads: 0 / 6")
        self.queue_var = tk.StringVar(value="Videos Pending in Queue: 0")
        self.archived_var = tk.StringVar(value="Total Successfully Archived: 0")
        self.failed_var = tk.StringVar(value="Total Failed: 0")
        
        self.create_metric_row(self.quota_var)
        self.create_metric_row(self.queue_var)
        self.create_metric_row(self.archived_var)
        self.create_metric_row(self.failed_var)
        
        # Refresh Button
        self.refresh_btn = tk.Button(self.root, text="Refresh Now", font=self.label_font, command=self.update_dashboard, bg="#dcdcdc", relief="groove")
        self.refresh_btn.pack(pady=20)
        
        # Update Job ID for cancellation
        self.update_job = None
        
        # Start the loop
        self.update_dashboard()
        
    def create_metric_row(self, var):
        lbl = tk.Label(self.metrics_frame, textvariable=var, font=self.label_font, bg="#f4f4f9", anchor="w")
        lbl.pack(fill="x", pady=5)
        
    def update_dashboard(self):
        # Update Status
        if is_uploader_running():
            self.status_label.config(text="Status: RUNNING", fg="green")
        else:
            self.status_label.config(text="Status: STOPPED", fg="red")
            
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
