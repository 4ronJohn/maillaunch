from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from campaign.database import CampaignDatabase, CampaignRecipient
from utils.logger import SendLogger


# Error raised when sending an email fails.
class SendError(Exception):
    def __init__(self, message: str, *, auth_error: bool = False):
        super().__init__(message)
        self.auth_error = auth_error


# Settings used by the sending engine.
@dataclass(frozen=True)
class EngineSettings:
    daily_limit: int = 100
    min_delay_seconds: float = 60
    max_delay_seconds: float = 180
    retry_attempts: int = 2
    retry_failed: bool = True
    provider: str = "gmail"


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
        clock: Callable[[], float] = time.monotonic,
        timer_interval: float = 0.1,
    ):
        self.database = database
        self.logger = logger
        self.provider = provider
        self.settings = settings
        self.sleep = sleep
        self.random_delay = random_delay
        self.refresh = refresh
        self.clock = clock
        self.timer_interval = timer_interval

    # Start the processing timer shown while an email is being processed.
    def _start_processing_timer(
        self,
    ) -> tuple[threading.Event, threading.Thread, float]:
        stop_event = threading.Event()
        started_at = self.clock()

        def update() -> None:
            while True:
                elapsed = self.clock() - started_at
                print(
                    f"\rProcessing... {elapsed:.1f}s",
                    end="",
                    flush=True,
                )

                if stop_event.wait(self.timer_interval):
                    return

        timer = threading.Thread(target=update, daemon=True)
        timer.start()

        return stop_event, timer, started_at

    # Stop the processing timer and display the final processing time.
    def _stop_processing_timer(
        self,
        stop_event: threading.Event,
        timer: threading.Thread,
        started_at: float,
    ) -> None:
        stop_event.set()
        timer.join()

        elapsed = self.clock() - started_at
        print(f"\rProcessing... {elapsed:.1f}s", flush=True)

    def run(self, campaign_id: str) -> None:
        # Get all recipients that still need to be sent.
        recipients = list(self.database.pending_recipients(campaign_id))
        total = len(recipients)

        if total == 0:
            self.database.set_campaign_status(campaign_id, "COMPLETE")
            print("No pending recipients.")
            return

        campaign_started_at = self.clock()

        for index, recipient in enumerate(recipients, start=1):
            # Stop sending when the daily limit is reached.
            if self.database.daily_sent_count() >= self.settings.daily_limit:
                self.database.mark_limit_reached(campaign_id)

                self.logger.record(
                    "LIMIT_REACHED",
                    campaign_id=campaign_id,
                    provider=self.settings.provider,
                )

                print("\nDaily send limit reached.")
                return

            print(f"\nSending {index}/{total}: {recipient.email}")

            stop_event, timer, started_at = self._start_processing_timer()

            try:
                # Wait for a random delay before sending.
                delay = self.random_delay(
                    self.settings.min_delay_seconds,
                    self.settings.max_delay_seconds,
                )

                self.sleep(delay)
                success = self._send_recipient(recipient)

            finally:
                self._stop_processing_timer(
                    stop_event,
                    timer,
                    started_at,
                )

            if success:
                print(f"SENT: {recipient.email}")
            else:
                print(f"FAILED: {recipient.email}")

        self.database.set_campaign_status(campaign_id, "COMPLETE")

        print("\nCampaign completed.")
        print(f"Total time: {self.clock() - campaign_started_at:.1f}s")

    def _send_recipient(self, recipient: CampaignRecipient) -> bool:
        # Calculate the maximum number of sending attempts.
        max_attempts = 1 + (
            self.settings.retry_attempts
            if self.settings.retry_failed
            else 0
        )

        refreshed = False
        attempt = 1

        while attempt <= max_attempts:
            self.database.mark_attempt(recipient.id)

            try:
                self.provider(recipient)

            except SendError as error:
                # Handle authentication errors by refreshing the token once.
                if (
                    error.auth_error
                    and not refreshed
                    and self.refresh is not None
                ):
                    refreshed = True

                    if self.refresh():
                        max_attempts += 1
                        attempt += 1
                        continue

                    self.database.mark_failed(
                        recipient.id,
                        str(error),
                    )

                    self.logger.record(
                        "FAILED",
                        campaign_id=recipient.campaign_id,
                        email=recipient.email,
                        name=recipient.name,
                        error="authentication refresh failed",
                        attempt=attempt,
                        provider=self.settings.provider,
                    )

                    return False

                # Final failed attempt.
                if attempt >= max_attempts:
                    self.database.mark_failed(
                        recipient.id,
                        str(error),
                    )

                    self.logger.record(
                        "FAILED",
                        campaign_id=recipient.campaign_id,
                        email=recipient.email,
                        name=recipient.name,
                        error=str(error),
                        attempt=attempt,
                        provider=self.settings.provider,
                    )

                    return False

                # Retry with exponential backoff.
                self.database.mark_retry(
                    recipient.id,
                    str(error),
                )

                delay = 2 ** (attempt - 1)

                self.logger.record(
                    "RETRY",
                    campaign_id=recipient.campaign_id,
                    email=recipient.email,
                    name=recipient.name,
                    error=str(error),
                    attempt=attempt,
                    provider=self.settings.provider,
                )

                self.sleep(delay)

                attempt += 1
                continue

            else:
                self.database.mark_sent(recipient.id)

                self.logger.record(
                    "SENT",
                    campaign_id=recipient.campaign_id,
                    email=recipient.email,
                    name=recipient.name,
                    attempt=attempt,
                    provider=self.settings.provider,
                )

                return True

        return False