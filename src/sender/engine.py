from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from campaign.database import CampaignDatabase, CampaignRecipient
from utils.logger import SendLogger


class SendError(Exception):
    def __init__(self, message: str, *, auth_error: bool = False):
        super().__init__(message)
        self.auth_error = auth_error


@dataclass(frozen=True)
class EngineSettings:
    daily_limit: int = 100
    min_delay_seconds: float = 60
    max_delay_seconds: float = 180
    retry_attempts: int = 2
    retry_failed: bool = True


class SendingEngine:
    def __init__(
        self,
        database: CampaignDatabase,
        logger: SendLogger,
        provider: Callable[[CampaignRecipient], None],
        settings: EngineSettings,
        *,
        sleep: Callable[[float], None] = time.sleep,
        random_delay: Callable[[float, float], float] = random.uniform,
        refresh: Callable[[], bool] | None = None,
    ):
        self.database = database
        self.logger = logger
        self.provider = provider
        self.settings = settings
        self.sleep = sleep
        self.random_delay = random_delay
        self.refresh = refresh

    def run(self, campaign_id: str) -> None:
        for recipient in self.database.pending_recipients(campaign_id):
            if self.database.daily_sent_count() >= self.settings.daily_limit:
                self.database.mark_limit_reached(campaign_id)
                self.logger.record("LIMIT_REACHED", campaign_id=campaign_id)
                return
            self._send_recipient(recipient)
            if self.database.pending_recipients(campaign_id):
                self.sleep(self.random_delay(self.settings.min_delay_seconds, self.settings.max_delay_seconds))
        self.database.set_campaign_status(campaign_id, "COMPLETE")

    def _send_recipient(self, recipient: CampaignRecipient) -> None:
        max_attempts = 1 + (self.settings.retry_attempts if self.settings.retry_failed else 0)
        refreshed = False
        for attempt in range(1, max_attempts + 1):
            self.database.mark_attempt(recipient.id)
            try:
                self.provider(recipient)
            except SendError as error:
                if error.auth_error and not refreshed and self.refresh is not None:
                    refreshed = True
                    if self.refresh():
                        continue
                    self.database.mark_failed(recipient.id, str(error))
                    self.logger.record("FAILED", campaign_id=recipient.campaign_id, email=recipient.email, name=recipient.name, error="authentication refresh failed", attempt=attempt)
                    return
                if attempt >= max_attempts:
                    self.database.mark_failed(recipient.id, str(error))
                    self.logger.record("FAILED", campaign_id=recipient.campaign_id, email=recipient.email, name=recipient.name, error=str(error), attempt=attempt)
                    return
                self.database.mark_retry(recipient.id, str(error))
                delay = 2 ** (attempt - 1)
                self.logger.record("RETRY", campaign_id=recipient.campaign_id, email=recipient.email, name=recipient.name, error=str(error), attempt=attempt)
                self.sleep(delay)
                continue
            else:
                self.database.mark_sent(recipient.id)
                self.logger.record("SENT", campaign_id=recipient.campaign_id, email=recipient.email, name=recipient.name, attempt=attempt)
                return
