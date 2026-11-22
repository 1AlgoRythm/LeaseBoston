"""SQLite storage shared by the MCP server and the landlord page.

Both processes (the stdio MCP server Claude Desktop starts, and the web server
that hosts the landlord page) open the same file, so WAL mode is on.
"""

import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "lease.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS landlords (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, company TEXT NOT NULL, email TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY, landlord_id TEXT NOT NULL REFERENCES landlords(id),
    title TEXT NOT NULL, neighborhood TEXT NOT NULL, address TEXT NOT NULL,
    lat REAL NOT NULL, lon REAL NOT NULL,
    rent INTEGER NOT NULL, beds INTEGER NOT NULL, baths REAL NOT NULL, sqft INTEGER NOT NULL,
    available_from TEXT NOT NULL, lease_months INTEGER NOT NULL,
    pets TEXT NOT NULL,            -- 'none' | 'cats' | 'cats_and_dogs'
    amenities TEXT NOT NULL,       -- JSON list
    description TEXT NOT NULL
);
-- The landlord's premade answers. listing_id NULL = applies to all their units.
CREATE TABLE IF NOT EXISTS saved_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    landlord_id TEXT NOT NULL REFERENCES landlords(id),
    listing_id TEXT REFERENCES listings(id),
    question TEXT NOT NULL, answer TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'landlord',   -- 'seed' | 'landlord' | 'from_reply'
    created_at TEXT NOT NULL
);
-- Every question a renter asked about a listing. This is what the landlord sees.
CREATE TABLE IF NOT EXISTS questions (
    ref TEXT PRIMARY KEY,                       -- handle the server mints, e.g. Q7F3K9
    listing_id TEXT NOT NULL REFERENCES listings(id),
    landlord_id TEXT NOT NULL REFERENCES landlords(id),
    question TEXT NOT NULL,
    status TEXT NOT NULL,   -- 'auto_answered' | 'not_sent' | 'waiting' | 'replied'
    matched_answer_id INTEGER REFERENCES saved_answers(id),
    match_score REAL,
    renter_name TEXT, channel TEXT, contact TEXT,
    reply TEXT,
    asked_at TEXT NOT NULL, sent_at TEXT, replied_at TEXT
);
-- Every notification, real or simulated. The page at /outbox shows it.
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_ref TEXT, channel TEXT NOT NULL, recipient TEXT NOT NULL,
    subject TEXT NOT NULL, body TEXT NOT NULL,
    status TEXT NOT NULL,   -- 'sent' | 'simulated' | 'failed'
    detail TEXT, created_at TEXT NOT NULL
);
-- How often each listing was shown in search results.
CREATE TABLE IF NOT EXISTS impressions (
    listing_id TEXT NOT NULL, shown_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_path() -> Path:
    return Path(os.environ.get("LEASE_DB", DEFAULT_DB))


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init(reset: bool = False) -> None:
    """Create tables and load the synthetic seed data on first run."""
    if reset and db_path().exists():
        for suffix in ("", "-wal", "-shm"):
            Path(str(db_path()) + suffix).unlink(missing_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM landlords").fetchone()[0] == 0:
            _seed(conn)


def _seed(conn: sqlite3.Connection) -> None:
    from . import seed_data

    conn.executemany(
        "INSERT INTO landlords VALUES (:id, :name, :company, :email)", seed_data.LANDLORDS
    )
    for row in seed_data.LISTINGS:
        conn.execute(
            """INSERT INTO listings VALUES (:id, :landlord_id, :title, :neighborhood, :address,
               :lat, :lon, :rent, :beds, :baths, :sqft, :available_from, :lease_months,
               :pets, :amenities, :description)""",
            {**row, "amenities": json.dumps(row["amenities"])},
        )
    for landlord_id, listing_id, q, a in seed_data.SAVED_ANSWERS:
        conn.execute(
            "INSERT INTO saved_answers (landlord_id, listing_id, question, answer, source, created_at)"
            " VALUES (?, ?, ?, ?, 'seed', ?)",
            (landlord_id, listing_id, q, a, now()),
        )


def new_ref(conn: sqlite3.Connection) -> str:
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L, easy to read aloud
    while True:
        ref = "Q" + "".join(secrets.choice(alphabet) for _ in range(5))
        if not conn.execute("SELECT 1 FROM questions WHERE ref = ?", (ref,)).fetchone():
            return ref


def listing_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["amenities"] = json.loads(d["amenities"])
    return d
