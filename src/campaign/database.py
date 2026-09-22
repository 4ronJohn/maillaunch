from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class CampaignRecipient:
    id: int
    campaign_id: str
    email: str
    name: str
    subject: str
    body: str
    status: str
    attempts: int
    error: str | None


class CampaignDatabase:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING'
            );
            CREATE TABLE IF NOT EXISTS recipients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL REFERENCES campaigns(id),
                email TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                attempts INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                sent_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_recipient_campaign_status
                ON recipients(campaign_id, status);
            CREATE INDEX IF NOT EXISTS idx_recipient_sent_at
                ON recipients(sent_at);
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def create_campaign(self, provider: str, messages: list[dict[str, str]]) -> str:
        campaign_id = f"c_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{uuid4().hex[:6]}"
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connection:
            self.connection.execute(
                "INSERT INTO campaigns(id, provider, created_at) VALUES (?, ?, ?)",
                (campaign_id, provider, created_at),
            )
            self.connection.executemany(
                """
                INSERT INTO recipients(campaign_id, email, name, subject, body)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (campaign_id, item["email"], item.get("name", ""), item["subject"], item["body"])
                    for item in messages
                ],
            )
        return campaign_id

    def pending_recipients(self, campaign_id: str) -> list[CampaignRecipient]:
        rows = self.connection.execute(
            """
            SELECT id, campaign_id, email, name, subject, body, status, attempts, error
            FROM recipients
            WHERE campaign_id = ? AND status IN ('PENDING', 'RETRY')
            ORDER BY id
            """,
            (campaign_id,),
        ).fetchall()
        return [CampaignRecipient(**dict(row)) for row in rows]

    def mark_attempt(self, recipient_id: int) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE recipients SET attempts = attempts + 1 WHERE id = ?",
                (recipient_id,),
            )

    def mark_sent(self, recipient_id: int) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE recipients SET status = 'SENT', error = NULL, sent_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), recipient_id),
            )

    def mark_failed(self, recipient_id: int, error: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE recipients SET status = 'FAILED', error = ? WHERE id = ?",
                (error, recipient_id),
            )

    def mark_retry(self, recipient_id: int, error: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE recipients SET status = 'RETRY', error = ? WHERE id = ?",
                (error, recipient_id),
            )

    def mark_limit_reached(self, campaign_id: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE campaigns SET status = 'LIMIT_REACHED' WHERE id = ?",
                (campaign_id,),
            )

    def set_campaign_status(self, campaign_id: str, status: str) -> None:
        with self.connection:
            self.connection.execute("UPDATE campaigns SET status = ? WHERE id = ?", (status, campaign_id))

    def campaign_provider(self, campaign_id: str) -> str:
        row = self.connection.execute("SELECT provider FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if row is None:
            raise ValueError(f"campaign not found: {campaign_id}")
        return str(row["provider"])

    def daily_sent_count(self, day: date | None = None) -> int:
        target = (day or date.today()).isoformat()
        row = self.connection.execute(
            "SELECT COUNT(*) AS count FROM recipients WHERE status = 'SENT' AND sent_at LIKE ?",
            (f"{target}%",),
        ).fetchone()
        return int(row["count"])

    def summary(self, campaign_id: str | None = None) -> dict[str, int]:
        where = "WHERE campaign_id = ?" if campaign_id else ""
        args = (campaign_id,) if campaign_id else ()
        rows = self.connection.execute(
            f"SELECT status, COUNT(*) AS count FROM recipients {where} GROUP BY status", args
        ).fetchall()
        return {row["status"]: int(row["count"]) for row in rows}

    def resumable_campaign(self) -> str | None:
        row = self.connection.execute(
            """
            SELECT c.id FROM campaigns c
            JOIN recipients r ON r.campaign_id = c.id
            WHERE r.status IN ('PENDING', 'RETRY')
            ORDER BY c.created_at DESC LIMIT 1
            """
        ).fetchone()
        return row["id"] if row else None
