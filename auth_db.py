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
                accountant_email TEXT DEFAULT '',
                accountant_name TEXT DEFAULT '',
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
        # Migraciones automáticas seguras para instalaciones existentes
        try:
            conn.execute("ALTER TABLE users ADD COLUMN accountant_email TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN accountant_name TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
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
        "SELECT id, name, email, password_hash, accountant_email, accountant_name, is_active FROM users WHERE email = ?",
        (email,)
    ).fetchone()
    conn.close()

    if not row or not row["is_active"]:
        return None

    if verify_password(password, row["password_hash"]):
        token = create_session(row["id"], row["email"], row["name"])
        return {
            "user_id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "accountant_email": row["accountant_email"] or "",
            "accountant_name": row["accountant_name"] or "",
            "token": token
        }
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
    row = conn.execute("""
        SELECT s.user_id, u.email, u.name, u.accountant_email, u.accountant_name 
        FROM sessions s
        JOIN users u ON s.user_id = u.id
        WHERE s.token = ? AND s.expires_at > ?
    """, (token, now_str)).fetchone()
    conn.close()
    if row:
        return {
            "user_id": row["user_id"],
            "email": row["email"],
            "name": row["name"],
            "accountant_email": row["accountant_email"] or "",
            "accountant_name": row["accountant_name"] or ""
        }
    return None

def get_user_profile(user_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute(
        "SELECT id, name, email, accountant_email, accountant_name, created_at FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()
    conn.close()
    if row:
        return {
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "accountant_email": row["accountant_email"] or "",
            "accountant_name": row["accountant_name"] or "",
            "created_at": row["created_at"]
        }
    return None

def update_user_profile(user_id: int, name: str, accountant_email: str = "", accountant_name: str = "") -> bool:
    name = name.strip()
    accountant_email = accountant_email.strip().lower()
    accountant_name = accountant_name.strip()
    if not name:
        return False

    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE users SET name = ?, accountant_email = ?, accountant_name = ? WHERE id = ?",
            (name, accountant_email, accountant_name, user_id)
        )
        conn.execute(
            "UPDATE sessions SET name = ? WHERE user_id = ?",
            (name, user_id)
        )
    conn.close()
    return True

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

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    email = email.strip().lower()
    conn = get_connection()
    row = conn.execute("SELECT id, name, email FROM users WHERE email = ? AND is_active = 1", (email,)).fetchone()
    conn.close()
    if row:
        return {"id": row["id"], "name": row["name"], "email": row["email"]}
    return None

def reset_password(email: str, new_password: str, code: str) -> Optional[Dict[str, Any]]:
    email = email.strip().lower()
    if not verify_code(email, code):
        return None
    pwd_hash = hash_password(new_password)
    conn = get_connection()
    try:
        with conn:
            conn.execute("UPDATE verification_codes SET used = 1 WHERE email = ? AND code = ?", (email, code))
            conn.execute("UPDATE users SET password_hash = ? WHERE email = ?", (pwd_hash, email))
            row = conn.execute("SELECT id, name, email, accountant_email, accountant_name FROM users WHERE email = ?", (email,)).fetchone()
            if row:
                token = create_session_for_user(row["id"], row["email"], row["name"], conn)
                return {
                    "user_id": row["id"],
                    "name": row["name"],
                    "email": row["email"],
                    "accountant_email": row["accountant_email"] or "",
                    "accountant_name": row["accountant_name"] or "",
                    "token": token
                }
    finally:
        conn.close()
    return None

# Inicializar DB al importar
init_db()
