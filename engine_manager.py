import threading
import time
import uploader

_engine_thread = None
_stop_event = threading.Event()
_wake_event = threading.Event()
_lock = threading.Lock()

def _run_worker():
    """Background worker running the uploader engine."""
    print("🎬 [ENGINE] Starting YouTube Auto Publisher Engine...")
    try:
        service = uploader.authenticate()
        uploader.main_loop(service, stop_event=_stop_event, wake_event=_wake_event)
    except Exception as e:
        print(f"⚠️ [ENGINE ERROR] {e}")
    print("🛑 [ENGINE] Uploader engine stopped.")

def is_running():
    """Returns True if the uploader engine thread is active."""
    global _engine_thread
    return _engine_thread is not None and _engine_thread.is_alive()

def start_engine():
    """Starts the engine in a background thread if not already running."""
    global _engine_thread, _stop_event, _wake_event
    with _lock:
        if is_running():
            return True
        _stop_event.clear()
        _wake_event.clear()
        _engine_thread = threading.Thread(target=_run_worker, daemon=True, name="UploaderEngineWorker")
        _engine_thread.start()
        return True

def stop_engine(timeout=5):
    """Signals the engine to stop and waits for completion."""
    global _engine_thread, _stop_event, _wake_event
    with _lock:
        if not is_running():
            return True
        _stop_event.set()
        _wake_event.set()
    
    if _engine_thread:
        _engine_thread.join(timeout=timeout)
    return not is_running()

def restart_engine():
    """Stops existing engine and starts a fresh instance."""
    stop_engine(timeout=3)
    time.sleep(0.5)
    return start_engine()

def wake_engine():
    """Interrupts idle sleep so new videos or actions process immediately."""
    _wake_event.set()
