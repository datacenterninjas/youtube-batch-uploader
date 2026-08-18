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
    "default_category": "Travel & Events",
    "default_privacy": "unlisted",
    "return_directory": "~/Downloads",
    "gemini_api_key": ""
}

def load_config():
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                user_cfg = json.load(f)
                config.update(user_cfg)
        except Exception as e:
            print(f"Warning: Could not read {CONFIG_FILE}, using defaults. Error: {e}")
    return config

def get_setting(key, default=None):
    cfg = load_config()
    return cfg.get(key, default if default is not None else DEFAULT_CONFIG.get(key))

def save_config(new_config):
    """Saves updated settings dictionary to config.json."""
    current = load_config()
    current.update(new_config)
    with open(CONFIG_FILE, "w") as f:
        json.dump(current, f, indent=4)
    return current
