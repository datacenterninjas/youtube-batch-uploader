import os
import webbrowser
import subprocess
from pathlib import Path
import rumps
import database
import config
import activity_tracker

class YouTubePublisherTrayApp(rumps.App):
    def __init__(self):
        super(YouTubePublisherTrayApp, self).__init__("🎬 YT Publisher", quit_button=None)
        self.menu = [
            rumps.MenuItem("🌐 Open Web Dashboard", callback=self.open_dashboard),
            None,
            rumps.MenuItem("📊 Daily Quota: Loading...", callback=None),
            rumps.MenuItem("⚡ Status: Idle", callback=None),
            None,
            rumps.MenuItem("📁 Open Staging Folder", callback=self.open_staging_folder),
            rumps.MenuItem("📁 Open Downloads Folder", callback=self.open_downloads_folder),
            None,
            rumps.MenuItem("Quit YouTube Auto Publisher", callback=self.quit_app)
        ]

    def open_dashboard(self, _):
        webbrowser.open("http://127.0.0.1:8000")

    def open_staging_folder(self, _):
        staging_dir = os.path.abspath("videos_to_upload")
        os.makedirs(staging_dir, exist_ok=True)
        subprocess.run(["open", staging_dir])

    def open_downloads_folder(self, _):
        return_dir = os.path.expanduser(config.get_setting("return_directory", "~/Downloads"))
        os.makedirs(return_dir, exist_ok=True)
        subprocess.run(["open", return_dir])

    def quit_app(self, _):
        rumps.quit_application()

    @rumps.timer(3)
    def update_status(self, _):
        try:
            # Update Quota
            import uploader
            quota_data = uploader.load_quota()
            count = quota_data.get("count", 0)
            max_quota = config.get_setting("daily_upload_limit", 6)
            self.menu["📊 Daily Quota: Loading..."].title = f"📊 Daily Uploads: {count} / {max_quota}"

            # Update Activity
            activity = activity_tracker.get_activity()
            if activity.get("active"):
                task = activity.get("task", "BUSY")
                prog = activity.get("progress", 0)
                self.title = f"🚀 {prog}%"
                self.menu["⚡ Status: Idle"].title = f"⚡ {activity.get('label', 'Processing...')}"
            else:
                self.title = "🎬 YT Publisher"
                self.menu["⚡ Status: Idle"].title = "🟢 System Idle (Ready)"
        except Exception:
            pass

if __name__ == "__main__":
    app = YouTubePublisherTrayApp()
    app.run()
