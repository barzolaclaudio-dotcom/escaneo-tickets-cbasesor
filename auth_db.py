import sqlite3
import os
import secrets
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

DB_PATH = Path(__file__).resolve().parent / "users.db"

def get_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS verification_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                name TEXT NOT NULL,
                code TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                email TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
    conn.close()

def hash_password(password: str) -> str:
    """Genera hash seguro usando PBKDF2-HMAC-SHA256 con salt aleatorio."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    return f"{salt}:{key.hex()}"

def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, key_hex = stored_hash.split(':')
        new_key = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        )
        return secrets.compare_digest(new_key.hex(), key_hex)
    except Exception:
        return False

def create_verification_code(email: str, name: str) -> str:
    email = email.strip().lower()
    name = name.strip()
    code = f"{secrets.randbelow(900000) + 100000}"
    expires_at = (datetime.utcnow() + timedelta(minutes=15)).isoformat()
    now_str = datetime.utcnow().isoformat()

    conn = get_connection()
    with conn:
        # Invalidar códigos anteriores no usados
        conn.execute(
            "UPDATE verification_codes SET used = 1 WHERE email = ? AND used = 0",
            (email,)
        )
        conn.execute(
            "INSERT INTO verification_codes (email, name, code, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (email, name, code, expires_at, now_str)
        )
    conn.close()
    return code

def verify_code(email: str, code: str) -> bool:
    email = email.strip().lower()
    code = code.strip()
    now_str = datetime.utcnow().isoformat()

    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM verification_codes WHERE email = ? AND code = ? AND used = 0 AND expires_at > ? ORDER BY id DESC LIMIT 1",
        (email, code, now_str)
    ).fetchone()
    conn.close()
    return row is not None

def register_user(name: str, email: str, password: str, code: str) -> Optional[Dict[str, Any]]:
    email = email.strip().lower()
    name = name.strip()
    if not verify_code(email, code):
        return None

    pwd_hash = hash_password(password)
    now_str = datetime.utcnow().isoformat()

    conn = get_connection()
    try:
        with conn:
            # Marcar código como usado
            conn.execute(
                "UPDATE verification_codes SET used = 1 WHERE email = ? AND code = ?",
                (email, code)
            )
            cursor = conn.execute(
                "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (name, email, pwd_hash, now_str)
            )
            user_id = cursor.lastrowid
            token = create_session_for_user(user_id, email, name, conn)
            return {"user_id": user_id, "name": name, "email": email, "token": token}
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()

def authenticate_user(email: str, password: str) -> Optional[Dict[str, Any]]:
    email = email.strip().lower()
    conn = get_connection()
    row = conn.execute(
        "SELECT id, name, email, password_hash, is_active FROM users WHERE email = ?",
        (email,)
    ).fetchone()
    conn.close()

    if not row or not row["is_active"]:
        return None

    if verify_password(password, row["password_hash"]):
        token = create_session(row["id"], row["email"], row["name"])
        return {"user_id": row["id"], "name": row["name"], "email": row["email"], "token": token}
    return None

def create_session_for_user(user_id: int, email: str, name: str, conn: sqlite3.Connection) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    expires_at = (now + timedelta(days=90)).isoformat() # Sesión válida por 90 días
    conn.execute(
        "INSERT INTO sessions (token, user_id, email, name, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
        (token, user_id, email, name, now.isoformat(), expires_at)
    )
    return token

def create_session(user_id: int, email: str, name: str) -> str:
    conn = get_connection()
    with conn:
        token = create_session_for_user(user_id, email, name, conn)
    conn.close()
    return token

def validate_session(token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    now_str = datetime.utcnow().isoformat()
    conn = get_connection()
    row = conn.execute(
        "SELECT user_id, email, name FROM sessions WHERE token = ? AND expires_at > ?",
        (token, now_str)
    ).fetchone()
    conn.close()
    if row:
        return {"user_id": row["user_id"], "email": row["email"], "name": row["name"]}
    return None

def delete_session(token: str):
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.close()

def user_exists(email: str) -> bool:
    email = email.strip().lower()
    conn = get_connection()
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return row is not None

# Inicializar DB al importar
init_db()
