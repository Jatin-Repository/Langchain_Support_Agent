from pathlib import Path
import sqlite3


# Project root
ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "ecommerce.db"
SQL_SEED_PATH = ROOT / "ecommerce_setup.sql"


def init_database(reset=False):
    """Initialize the SQLite database using the SQL seed file."""

    if DB_PATH.exists() and not reset:
        raise FileExistsError("Database already exists. Back it up before using --reset; reset deletes existing business records.")

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
    import argparse
    parser = argparse.ArgumentParser(description="Initialize demo business data")
    parser.add_argument("--reset", action="store_true", help="Delete existing data and recreate demo records")
    args = parser.parse_args()
    db_path = init_database(reset=args.reset)
    print(f"Database initialized at: {db_path}")


if __name__ == "__main__":
    main()
