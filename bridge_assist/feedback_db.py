"""SQLite feedback database for tracking taste engine learning.

Records every processed file detection: which NEF it matched, what channel
was inferred, and how that compares to the original AI scores. Enables
accuracy trending over time (the "learning curve" metric).
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    nef_filename TEXT,
    nef_path TEXT,
    processed_path TEXT NOT NULL,
    processed_ext TEXT,
    folder_name TEXT,
    match_method TEXT,
    match_confidence REAL,
    inferred_channel TEXT,
    inference_method TEXT,
    inference_confidence REAL,
    inference_signals TEXT,
    original_scores TEXT,
    original_top_channel TEXT,
    original_top_confidence REAL,
    is_confirmation INTEGER,
    tag TEXT
);

CREATE INDEX IF NOT EXISTS idx_feedback_nef ON feedback(nef_filename);
CREATE INDEX IF NOT EXISTS idx_feedback_channel ON feedback(inferred_channel);
CREATE INDEX IF NOT EXISTS idx_feedback_tag ON feedback(tag);
CREATE INDEX IF NOT EXISTS idx_feedback_timestamp ON feedback(timestamp);
"""


class FeedbackDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self):
        cur = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if not cur.fetchone():
            self.conn.executescript(SCHEMA_SQL)
            self.conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
            )
            self.conn.commit()

    def record(
        self,
        processed_path: Path,
        nef_filename: str | None,
        nef_path: str | None,
        match_method: str,
        match_confidence: float,
        inferred_channel: str,
        inference_method: str,
        inference_confidence: float,
        inference_signals: dict,
        original_scores: list[dict],
        tag: str | None = None,
    ) -> int:
        """Record a feedback entry. Returns the row ID."""
        original_top = None
        original_top_conf = None
        if original_scores:
            top = max(original_scores, key=lambda s: s["confidence"])
            original_top = top["channel"]
            original_top_conf = top["confidence"]

        is_confirmation = None
        if original_top and inferred_channel:
            is_confirmation = 1 if inferred_channel == original_top else 0

        folder_name = processed_path.parent.name

        cur = self.conn.execute(
            """INSERT INTO feedback (
                timestamp, nef_filename, nef_path, processed_path, processed_ext,
                folder_name, match_method, match_confidence,
                inferred_channel, inference_method, inference_confidence,
                inference_signals, original_scores, original_top_channel,
                original_top_confidence, is_confirmation, tag
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                nef_filename,
                nef_path,
                str(processed_path),
                processed_path.suffix.lower(),
                folder_name,
                match_method,
                match_confidence,
                inferred_channel,
                inference_method,
                inference_confidence,
                json.dumps(inference_signals),
                json.dumps(original_scores),
                original_top,
                original_top_conf,
                is_confirmation,
                tag,
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def recent(self, limit: int = 20, tag: str | None = None) -> list[dict]:
        """Get recent feedback entries."""
        if tag:
            rows = self.conn.execute(
                "SELECT * FROM feedback WHERE tag = ? ORDER BY timestamp DESC LIMIT ?",
                (tag, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM feedback ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def summary(self, tag: str | None = None) -> dict:
        """Aggregate feedback stats per channel."""
        where = "WHERE tag = ?" if tag else ""
        params = (tag,) if tag else ()

        rows = self.conn.execute(
            f"""SELECT
                inferred_channel,
                COUNT(*) as total,
                SUM(CASE WHEN is_confirmation = 1 THEN 1 ELSE 0 END) as confirmations,
                SUM(CASE WHEN is_confirmation = 0 THEN 1 ELSE 0 END) as corrections,
                SUM(CASE WHEN is_confirmation IS NULL THEN 1 ELSE 0 END) as unmatched,
                AVG(inference_confidence) as avg_confidence
            FROM feedback {where}
            GROUP BY inferred_channel
            ORDER BY total DESC""",
            params,
        ).fetchall()

        return {
            "channels": [dict(r) for r in rows],
            "total": sum(r["total"] for r in rows),
        }

    def accuracy(self, tag: str | None = None) -> dict:
        """Compute accuracy metrics: how often the AI's top pick matched the actual channel."""
        where = "WHERE is_confirmation IS NOT NULL"
        params: tuple = ()
        if tag:
            where += " AND tag = ?"
            params = (tag,)

        row = self.conn.execute(
            f"""SELECT
                COUNT(*) as total,
                SUM(CASE WHEN is_confirmation = 1 THEN 1 ELSE 0 END) as correct,
                SUM(CASE WHEN is_confirmation = 0 THEN 1 ELSE 0 END) as incorrect
            FROM feedback {where}""",
            params,
        ).fetchone()

        total = row["total"]
        correct = row["correct"]
        rate = correct / total if total > 0 else 0.0

        corrections = self.conn.execute(
            f"""SELECT
                original_top_channel,
                inferred_channel,
                COUNT(*) as count
            FROM feedback
            {where} AND is_confirmation = 0
            GROUP BY original_top_channel, inferred_channel
            ORDER BY count DESC""",
            params,
        ).fetchall()

        return {
            "total": total,
            "correct": correct,
            "incorrect": row["incorrect"],
            "accuracy_rate": round(rate, 3),
            "common_corrections": [dict(r) for r in corrections],
        }

    def close(self):
        self.conn.close()
