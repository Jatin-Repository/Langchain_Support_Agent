from pathlib import Path
import sqlite3


# Project root
ROOT = Path(__file__).resolve().parents[2]
print(f"Project root: {ROOT}")
DB_PATH = ROOT / "ecommerce.db"
SQL_SEED_PATH = ROOT / "ecommerce_setup.sql"


def init_database():
    """Initialize the SQLite database using the SQL seed file."""

    # Ensure parent folder exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Read SQL seed file
    sql = SQL_SEED_PATH.read_text(encoding="utf-8")

    # Create/populate database
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(sql)
        conn.commit()

    return DB_PATH


def main():
    db_path = init_database()
    print(f"Database initialized at: {db_path}")


if __name__ == "__main__":
    main()
