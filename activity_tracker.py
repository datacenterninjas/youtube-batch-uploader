import datetime

current_activity = {
    "task": "IDLE",
    "label": "🟢 System Idle — All background processes ready",
    "progress": 0,
    "active": False,
    "video_id": None,
    "updated_at": datetime.datetime.now().strftime("%H:%M:%S")
}

video_progress = {}

def set_activity(task_name, label, progress=0, active=True, video_id=None):
    """Sets current active system task (Merging, Vision AI, Frame Extraction, Uploading)."""
    global current_activity
    current_activity = {
        "task": task_name,
        "label": label,
        "progress": int(progress),
        "active": active,
        "video_id": video_id,
        "updated_at": datetime.datetime.now().strftime("%H:%M:%S")
    }
    if video_id:
        video_progress[str(video_id)] = {
            "task": task_name,
            "label": label,
            "progress": int(progress),
            "active": active
        }

def update_video_progress(video_id, task, label, progress, active=True):
    """Updates progress for a specific video and sets system activity."""
    video_progress[str(video_id)] = {
        "task": task,
        "label": label,
        "progress": int(progress),
        "active": active
    }
    set_activity(task, label, progress, active, video_id=video_id)

def get_video_progress(video_id):
    return video_progress.get(str(video_id), {"active": False, "progress": 0, "label": ""})

def get_activity():
    """Returns current system activity state including per-video progress dictionary."""
    return {
        **current_activity,
        "video_progress": video_progress
    }

def clear_activity(video_id=None):
    """Resets activity state to Idle."""
    global current_activity
    if video_id and str(video_id) in video_progress:
        video_progress.pop(str(video_id), None)
    current_activity = {
        "task": "IDLE",
        "label": "🟢 System Idle — All background processes ready",
        "progress": 0,
        "active": False,
        "video_id": None,
        "updated_at": datetime.datetime.now().strftime("%H:%M:%S")
    }
