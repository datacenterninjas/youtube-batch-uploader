import json
import os

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "daily_upload_limit": 6,
    "file_stability_seconds": 5,
    "max_upload_retries": 5,
    "approval_mode": "review",
    "ai_enabled": True,
    "transcription_enabled": True,
    "thumbnail_analysis_enabled": True,
    "generate_chapters": True,
    "default_category": "Travel & Events"
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                # Merge defaults for any missing keys
                for k, v in DEFAULT_CONFIG.items():
                    config.setdefault(k, v)
                return config
        except Exception as e:
            print(f"Warning: Could not read {CONFIG_FILE}, using defaults. Error: {e}")
    return DEFAULT_CONFIG.copy()

def get_setting(key, default=None):
    cfg = load_config()
    return cfg.get(key, default if default is not None else DEFAULT_CONFIG.get(key))
