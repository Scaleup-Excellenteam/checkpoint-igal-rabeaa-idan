import os
import sqlite3
import dbm
import json
from typing import Optional, List, Dict, Any

# Resolve database file paths relative to the Server directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RELATIONAL_DB_PATH = os.path.join(BASE_DIR, "users.db")
KV_STORE_PATH = os.path.join(BASE_DIR, "messages_kv")


# ==========================================
# RELATIONAL STORE: Users & Authentication
# ==========================================

def get_db_connection() -> sqlite3.Connection:
    """Returns a SQLite database connection with row factory enabled."""
    conn = sqlite3.connect(RELATIONAL_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_relational_db() -> None:
    """Initialize SQLite database and create the 'users' table if it doesn't exist."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()


def db_insert_user(username: str, password_hash: str) -> bool:
    """
    Insert a new user with their password hash into the relational DB.
    Returns True if successful, False if the username already exists.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?);",
                (username.strip(), password_hash)
            )
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        # Duplicate username (UNIQUE constraint failed)
        return False


def get_user_hash(username: str) -> Optional[str]:
    """
    Retrieve a user's salted password hash by username for validation.
    Returns the password_hash string if found, otherwise None.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT password_hash FROM users WHERE username = ?;",
            (username.strip(),)
        )
        row = cursor.fetchone()
        return row["password_hash"] if row else None


def get_all_users() -> List[str]:
    """
    Retrieve a list of all registered usernames from the relational DB.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM users ORDER BY username ASC;")
        rows = cursor.fetchall()
        return [row["username"] for row in rows]


# ==========================================
# KEY-VALUE STORE: Chat History & Sync Queues
# ==========================================

def init_kv_store() -> None:
    """Initialize the KV store file for chat messages."""
    with dbm.open(KV_STORE_PATH, "c") as db:
        pass


def save_message(message_id: str, channel_id: str, content: str, timestamp: str) -> None:
    """
    Store a chat message in the KV store.
    The key format is '{channel_id}:{message_id}' for quick lookup.
    """
    key = f"{channel_id}:{message_id}".encode("utf-8")
    data = {
        "message_id": message_id,
        "channel_id": channel_id,
        "content": content,
        "timestamp": timestamp
    }
    value = json.dumps(data).encode("utf-8")

    with dbm.open(KV_STORE_PATH, "c") as db:
        db[key] = value


def get_recent_messages(channel_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Retrieve recent messages for a specific room/channel from the KV store.
    """
    messages = []
    prefix = f"{channel_id}:".encode("utf-8")

    with dbm.open(KV_STORE_PATH, "r") as db:
        for key in db.keys():
            if key.startswith(prefix):
                raw_data = db[key]
                messages.append(json.loads(raw_data.decode("utf-8")))

    # Sort messages by timestamp ascending
    messages.sort(key=lambda msg: msg.get("timestamp", ""))
    return messages[-limit:]
