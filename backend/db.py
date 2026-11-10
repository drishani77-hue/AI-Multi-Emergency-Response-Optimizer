import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "database" / "resqtech.db"
SCHEMA_PATH = PROJECT_ROOT / "database" / "schema.sql"


def connect_database(db_path: Path | str = DATABASE_PATH) -> sqlite3.Connection:
    """Create a configured SQLite connection."""

    connection = sqlite3.connect(
        str(db_path),
        timeout=5.0,
        isolation_level=None,
    )

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")

    return connection


def initialize_database() -> Path:
    """Create the project database and initialize its schema."""

    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Database schema not found: {SCHEMA_PATH}")

    connection = connect_database()

    try:
        journal_mode = connection.execute(
            "PRAGMA journal_mode = WAL"
        ).fetchone()[0]

        if journal_mode.lower() != "wal":
            raise RuntimeError(
                f"Could not enable WAL mode. Current mode: {journal_mode}"
            )

        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        connection.executescript(schema)

    finally:
        connection.close()

    return DATABASE_PATH