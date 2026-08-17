import sqlite3
import hashlib
import os
from datetime import datetime
from pathlib import Path

DB_FILE = "youtube_publisher.db"

def get_connection():
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        
        # Videos table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            filename TEXT NOT NULL,
            file_hash TEXT UNIQUE,
            file_size INTEGER,
            duration REAL,
            resolution TEXT,
            frame_rate REAL,
            privacy TEXT DEFAULT 'unlisted',
            status TEXT DEFAULT 'DISCOVERED',
            title TEXT,
            description TEXT,
            tags TEXT,
            category TEXT,
            playlist TEXT,
            transcript TEXT,
            ai_confidence REAL,
            youtube_video_id TEXT,
            youtube_url TEXT,
            upload_attempts INTEGER DEFAULT 0,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            analyzed_at TIMESTAMP,
            approved_at TIMESTAMP,
            uploaded_at TIMESTAMP,
            archived_at TIMESTAMP
        )
        """)
        
        # Upload attempts table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS upload_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL,
            attempt_number INTEGER NOT NULL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            status TEXT NOT NULL,
            error TEXT,
            retry_delay INTEGER DEFAULT 0,
            FOREIGN KEY (video_id) REFERENCES videos (id)
        )
        """)
        
        # Analysis table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL,
            analysis_type TEXT NOT NULL,
            result TEXT,
            model TEXT,
            confidence REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (video_id) REFERENCES videos (id)
        )
        """)
        
        conn.commit()

def calculate_file_hash(filepath, chunk_size=8192):
    """Calculates SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
    return sha256.hexdigest()

def get_video_by_hash(file_hash):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM videos WHERE file_hash = ?", (file_hash,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_video_by_path(file_path):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM videos WHERE file_path = ?", (str(file_path),))
        row = cursor.fetchone()
        return dict(row) if row else None

def register_video(file_path, privacy_status):
    """Registers a video file in the DB if not present, calculates hash and handles duplicate detection."""
    p = Path(file_path)
    file_size = p.stat().st_size if p.exists() else 0
    file_hash = calculate_file_hash(file_path)
    
    existing = get_video_by_hash(file_hash)
    if existing:
        return existing, True  # (video_dict, is_duplicate)
        
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO videos (file_path, filename, file_hash, file_size, privacy, status, title)
            VALUES (?, ?, ?, ?, ?, 'DISCOVERED', ?)
        """, (str(file_path), p.name, file_hash, file_size, privacy_status.lower(), p.stem))
        conn.commit()
        video_id = cursor.lastrowid
        
    return get_video_by_id(video_id), False

def get_video_by_id(video_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM videos WHERE id = ?", (video_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def update_video_status(video_id, status, error_message=None, youtube_video_id=None, youtube_url=None):
    with get_connection() as conn:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        extra_fields = ""
        params = [status]
        
        if error_message is not None:
            extra_fields += ", error_message = ?"
            params.append(error_message)
            
        if youtube_video_id is not None:
            extra_fields += ", youtube_video_id = ?"
            params.append(youtube_video_id)
            
        if youtube_url is not None:
            extra_fields += ", youtube_url = ?"
            params.append(youtube_url)
            
        if status == 'UPLOADED':
            extra_fields += ", uploaded_at = ?"
            params.append(now)
        elif status == 'ARCHIVED':
            extra_fields += ", archived_at = ?"
            params.append(now)
        elif status == 'ANALYZED':
            extra_fields += ", analyzed_at = ?"
            params.append(now)
            
        params.append(video_id)
        
        query = f"UPDATE videos SET status = ? {extra_fields} WHERE id = ?"
        cursor.execute(query, params)
        conn.commit()

def increment_upload_attempts(video_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE videos SET upload_attempts = upload_attempts + 1 WHERE id = ?", (video_id,))
        conn.commit()

def log_attempt(video_id, attempt_number, status, error=None, retry_delay=0):
    with get_connection() as conn:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO upload_attempts (video_id, attempt_number, started_at, completed_at, status, error, retry_delay)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (video_id, attempt_number, now, now, status, error, retry_delay))
        conn.commit()

def get_pending_videos():
    """Returns videos in DISCOVERED, READY_TO_UPLOAD, or STABILIZING state."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM videos WHERE status IN ('DISCOVERED', 'READY_TO_UPLOAD') ORDER BY id ASC")
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

def update_video_metadata(video_id, duration, resolution, frame_rate):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE videos 
            SET duration = ?, resolution = ?, frame_rate = ? 
            WHERE id = ?
        """, (duration, resolution, frame_rate, video_id))
        conn.commit()

def get_db_stats():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, COUNT(*) as count FROM videos GROUP BY status")
        rows = cursor.fetchall()
        return {r["status"]: r["count"] for r in rows}
