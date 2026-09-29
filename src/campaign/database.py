from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4


# Recipient data stored in the database.
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


# Scheduled campaign data stored in the database.
@dataclass(frozen=True)
class ScheduledCampaign:
    campaign_id: str
    scheduled_at: str
    min_delay_seconds: float
    max_delay_seconds: float


class CampaignDatabase:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

        # Create the database tables and indexes if they don't exist.
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
            CREATE TABLE IF NOT EXISTS scheduled_campaigns (
                campaign_id TEXT PRIMARY KEY REFERENCES campaigns(id),
                scheduled_at TEXT NOT NULL,
                min_delay_seconds REAL NOT NULL,
                max_delay_seconds REAL NOT NULL
            );
            """
        )

        # Check for the old scheduled campaign schema.
        columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(scheduled_campaigns)")
        }

        if "task_name" in columns:
            # Migrate the old scheduled campaign table to the current schema.
            self.connection.executescript(
                """
                ALTER TABLE scheduled_campaigns RENAME TO scheduled_campaigns_legacy;
                CREATE TABLE scheduled_campaigns (
                    campaign_id TEXT PRIMARY KEY REFERENCES campaigns(id),
                    scheduled_at TEXT NOT NULL,
                    min_delay_seconds REAL NOT NULL,
                    max_delay_seconds REAL NOT NULL
                );
                INSERT INTO scheduled_campaigns(
                    campaign_id, scheduled_at, min_delay_seconds, max_delay_seconds
                )
                SELECT campaign_id, scheduled_at, min_delay_seconds, max_delay_seconds
                FROM scheduled_campaigns_legacy;
                DROP TABLE scheduled_campaigns_legacy;
                """
            )

        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    # Create a campaign and store its recipients.
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

    # Get recipients that are waiting to be sent or retried.
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

    # Increment the recipient's attempt count.
    def mark_attempt(self, recipient_id: int) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE recipients SET attempts = attempts + 1 WHERE id = ?",
                (recipient_id,),
            )

    # Mark a recipient as successfully sent.
    def mark_sent(self, recipient_id: int) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE recipients SET status = 'SENT', error = NULL, sent_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), recipient_id),
            )

    # Mark a recipient as permanently failed.
    def mark_failed(self, recipient_id: int, error: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE recipients SET status = 'FAILED', error = ? WHERE id = ?",
                (error, recipient_id),
            )

    # Mark a recipient for another attempt.
    def mark_retry(self, recipient_id: int, error: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE recipients SET status = 'RETRY', error = ? WHERE id = ?",
                (error, recipient_id),
            )

    # Mark a campaign as having reached the daily limit.
    def mark_limit_reached(self, campaign_id: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE campaigns SET status = 'LIMIT_REACHED' WHERE id = ?",
                (campaign_id,),
            )

    # Schedule a campaign for a future time.
    def schedule_campaign(
        self,
        campaign_id: str,
        scheduled_at: str,
        min_delay_seconds: float,
        max_delay_seconds: float,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO scheduled_campaigns(
                    campaign_id, scheduled_at,
                    min_delay_seconds, max_delay_seconds
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    campaign_id,
                    scheduled_at,
                    min_delay_seconds,
                    max_delay_seconds,
                ),
            )
            self.connection.execute(
                "UPDATE campaigns SET status = 'SCHEDULED' WHERE id = ?",
                (campaign_id,),
            )

    # Get the scheduled details for a campaign.
    def scheduled_campaign(self, campaign_id: str) -> ScheduledCampaign | None:
        row = self.connection.execute(
            """
                 SELECT campaign_id, scheduled_at,
                   min_delay_seconds, max_delay_seconds
            FROM scheduled_campaigns
            WHERE campaign_id = ?
            """,
            (campaign_id,),
        ).fetchone()

        return ScheduledCampaign(**dict(row)) if row else None

    # Move a scheduled campaign back to pending.
    def start_scheduled_campaign(self, campaign_id: str) -> bool:
        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE campaigns
                SET status = 'PENDING'
                WHERE id = ? AND status = 'SCHEDULED'
                """,
                (campaign_id,),
            )

        return cursor.rowcount == 1

    # Remove the schedule for a campaign.
    def delete_scheduled_campaign(self, campaign_id: str) -> None:
        with self.connection:
            self.connection.execute(
                "DELETE FROM scheduled_campaigns WHERE campaign_id = ?",
                (campaign_id,),
            )

    # Update the current campaign status.
    def set_campaign_status(self, campaign_id: str, status: str) -> None:
        with self.connection:
            self.connection.execute("UPDATE campaigns SET status = ? WHERE id = ?", (status, campaign_id))

    # Get the email provider used by a campaign.
    def campaign_provider(self, campaign_id: str) -> str:
        row = self.connection.execute("SELECT provider FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()

        if row is None:
            raise ValueError(f"campaign not found: {campaign_id}")

        return str(row["provider"])

    # Count emails successfully sent on a specific day.
    def daily_sent_count(self, day: date | None = None) -> int:
        target = (day or date.today()).isoformat()

        row = self.connection.execute(
            "SELECT COUNT(*) AS count FROM recipients WHERE status = 'SENT' AND sent_at LIKE ?",
            (f"{target}%",),
        ).fetchone()

        return int(row["count"])

    # Return recipient counts grouped by status.
    def summary(self, campaign_id: str | None = None) -> dict[str, int]:
        where = "WHERE campaign_id = ?" if campaign_id else ""
        args = (campaign_id,) if campaign_id else ()

        rows = self.connection.execute(
            f"SELECT status, COUNT(*) AS count FROM recipients {where} GROUP BY status", args
        ).fetchall()

        return {row["status"]: int(row["count"]) for row in rows}

    # Find the most recent campaign that can be resumed.
    def resumable_campaign(self) -> str | None:
        row = self.connection.execute(
            """
            SELECT c.id FROM campaigns c
            JOIN recipients r ON r.campaign_id = c.id
            WHERE r.status IN ('PENDING', 'RETRY') AND c.status != 'SCHEDULED'
            ORDER BY c.created_at DESC LIMIT 1
            """
        ).fetchone()

        return row["id"] if row else None