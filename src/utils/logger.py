from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SendLogger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        status: str,
        *,
        campaign_id: str,
        email: str | None = None,
        name: str | None = None,
        error: str | None = None,
        attempt: int | None = None,
        provider: str | None = None,
    ) -> None:
        event: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "provider": provider,
            "email": email,
            "name": name,
            "campaign_id": campaign_id,
        }

        if error is not None:
            event["error"] = error

        if attempt is not None:
            event["attempt"] = attempt

        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True) + "\n")

    def read_events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

        events: list[dict[str, Any]] = []

        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))

        return events
