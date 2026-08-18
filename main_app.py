import os
import sys
import time
import threading
import webbrowser
import uvicorn

import database
import config
from uploader import authenticate, main_loop

def run_fastapi_server():
    """Runs FastAPI Web UI server."""
    from app import app
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")

def run_uploader_loop():
    """Runs YouTube Auto Publisher engine loop."""
    try:
        service = authenticate()
        main_loop(service)
    except Exception as e:
        print(f"Uploader engine error: {e}")

def open_browser():
    """Opens Web Dashboard in default browser after server starts."""
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:8000")

def main():
    print("🚀 Launching YouTube Auto Publisher V2 Desktop App...")
    
    # Initialize DB & Directories
    database.init_db()
    os.makedirs("videos_to_upload/Public", exist_ok=True)
    os.makedirs("videos_to_upload/Private", exist_ok=True)
    os.makedirs("videos_to_upload/Unlisted", exist_ok=True)
    os.makedirs("uploaded_archive", exist_ok=True)
    os.makedirs("failed_to_upload", exist_ok=True)
    os.makedirs("processing", exist_ok=True)

    # 1. Start FastAPI server thread
    web_thread = threading.Thread(target=run_fastapi_server, daemon=True)
    web_thread.start()

    # 2. Start Uploader engine thread
    uploader_thread = threading.Thread(target=run_uploader_loop, daemon=True)
    uploader_thread.start()

    # 3. Open Web UI in Browser
    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()

    print("✨ YouTube Auto Publisher V2 is running at http://127.0.0.1:8000")
    print("Press CTRL+C in terminal or Quit app to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping YouTube Auto Publisher V2...")

if __name__ == "__main__":
    main()
