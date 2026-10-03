from pathlib import Path
import sqlite3
from typing import TypedDict


class UserRecord(TypedDict):
    email: str
    full_name: str
    role: str


def authenticate_user(
    email: str,
    password: str,
    role: str | None = None
) -> UserRecord | None:
    """Authenticate a user against the SQLite users table."""

    # Resolve project root
    root = Path(__file__).resolve().parents[2]

    # Resolve database path
    db_path = root / "ecommerce.db"

    # Base parameterized query
    query = """
        SELECT email, full_name, role
        FROM users
        WHERE email = ? AND password = ?
    """

    params = [email, password]

    # Optional role filter
    if role is not None:
        query += " AND role = ?"
        params.append(role)

    # Execute query
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(query, params)
        row = cursor.fetchone()

    # No matching user
    if row is None:
        return None

    # Return UserRecord
    return {
        "email": row[0],
        "full_name": row[1],
        "role": row[2],
    }

