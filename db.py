"""Database connection and setup helpers."""
import sqlite3
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = PROJECT_DIR / "db" / "schema.sql"
DB_PATH = PROJECT_DIR / "db" / "cafe.db"


def get_connection(db_path=DB_PATH):
    """Open a connection with foreign keys enforced."""
    conn = sqlite3.connect(db_path)
    # SQLite ignores foreign keys unless they are enabled on every connection.
    conn.execute("PRAGMA foreign_keys = ON")
    # Lets us read columns by name: row["name"] instead of row[1].
    conn.row_factory = sqlite3.Row
    return conn


def create_database(db_path=DB_PATH):
    """Build an empty database from schema.sql, replacing any existing file."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = get_connection(db_path)
    try:
        # utf-8 is needed on Windows because schema.sql contains Greek text.
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    create_database()
    print(f"Database created: {DB_PATH}")
