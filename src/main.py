from __future__ import annotations

import argparse
import os
import re
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from auth.gmail import authenticate as authenticate_gmail
from auth.gmail import refresh as refresh_gmail
from auth.microsoft import authenticate as authenticate_microsoft
from auth.microsoft import refresh as refresh_microsoft
from auth.storage import load_token
from campaign.campaign import build_messages
from campaign.database import CampaignDatabase
from sender.engine import EngineSettings, SendingEngine
from sender.gmail import GmailSender
from sender.microsoft import MicrosoftSender
from utils.config import ConfigError, Settings, load_settings
from utils.csv_parser import parse_csv
from utils.logger import SendLogger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="maillaunch",
        description="Send personalized campaigns through Gmail or Microsoft Graph.",
    )

    parser.add_argument(
        "--config",
        help="Path to a YAML configuration file",
    )

    subparsers = parser.add_subparsers(dest="command")

    auth = subparsers.add_parser(
        "auth",
        help="Authenticate a provider",
    )
    auth.add_argument(
        "provider",
        choices=("gmail", "microsoft"),
    )

    send = subparsers.add_parser(
        "send",
        help="Start a campaign",
    )
    send.add_argument(
        "--provider",
        choices=("gmail", "microsoft"),
    )
    send.add_argument(
        "--csv",
        required=True,
    )
    send.add_argument(
        "--subject",
        required=True,
    )
    send.add_argument(
        "--body-file",
        required=True,
    )
    send.add_argument(
        "--min-delay",
        type=float,
    )
    send.add_argument(
        "--max-delay",
        type=float,
    )
    send.add_argument(
        "--at",
        dest="scheduled_at",
    )

    subparsers.add_parser(
        "status",
        help="Show campaign status",
    )

    resume = subparsers.add_parser(
        "resume",
        help="Resume an interrupted campaign",
    )
    resume.add_argument(
        "campaign_id",
        nargs="?",
    )
    resume.add_argument(
        "--min-delay",
        type=float,
    )
    resume.add_argument(
        "--max-delay",
        type=float,
    )

    subparsers.add_parser(
        "log",
        help="Prints send log",
    )

    return parser


def _data_paths(
    database_path: str | Path | None = None,
    log_path: str | Path | None = None,
) -> tuple[Path, Path]:
    data_dir = Path(
        os.getenv(
            "MAILLAUNCH_DATA_DIR",
            ".maillaunch",
        )
    )

    database = Path(
        database_path
        or os.getenv(
            "MAILLAUNCH_DB_PATH",
            data_dir / "campaigns.sqlite3",
        )
    )

    log = Path(
        log_path
        or os.getenv(
            "MAILLAUNCH_LOG_PATH",
            data_dir / "send.jsonl",
        )
    )

    return database, log


def _engine_settings(
    settings: Settings,
    args: argparse.Namespace,
    *,
    provider: str = "gmail",
    min_delay: float | None = None,
    max_delay: float | None = None,
) -> EngineSettings:
    cli_min_delay = getattr(
        args,
        "min_delay",
        None,
    )

    cli_max_delay = getattr(
        args,
        "max_delay",
        None,
    )

    effective_min_delay = (
        settings.send.min_delay_seconds
        if cli_min_delay is None
        else cli_min_delay
    )

    effective_max_delay = (
        settings.send.max_delay_seconds
        if cli_max_delay is None
        else cli_max_delay
    )

    if min_delay is not None:
        effective_min_delay = min_delay

    if max_delay is not None:
        effective_max_delay = max_delay

    if effective_min_delay < 0 or effective_max_delay < 0:
        raise ConfigError(
            "send delay values cannot be negative"
        )

    if effective_max_delay < effective_min_delay:
        raise ConfigError(
            "send delay bounds are invalid"
        )

    return EngineSettings(
        daily_limit=settings.daily_limit,
        min_delay_seconds=effective_min_delay,
        max_delay_seconds=effective_max_delay,
        retry_attempts=settings.send.retry_attempts,
        retry_failed=settings.send.retry_failed,
        provider=provider,
    )


def _provider_sender(
    provider: str,
    settings: Settings,
):
    token = load_token(provider)

    if token is None:
        raise ConfigError(
            f"no {provider} OAuth token found; "
            f"run 'maillaunch auth {provider}' first"
        )

    if provider == "gmail":
        sender = GmailSender(token.access_token)

        def refresh() -> bool:
            if (
                not settings.gmail_client_id
                or not settings.gmail_client_secret
            ):
                return False

            refreshed = refresh_gmail(
                token,
                settings.gmail_client_id,
                settings.gmail_client_secret,
            )

            if refreshed is None:
                return False

            sender.access_token = refreshed.access_token
            return True

        return sender, refresh

    sender = MicrosoftSender(token.access_token)

    def refresh() -> bool:
        if not settings.microsoft_client_id:
            return False

        refreshed = refresh_microsoft(
            token,
            settings.microsoft_client_id,
        )

        if refreshed is None:
            return False

        sender.access_token = refreshed.access_token
        return True

    return sender, refresh


def _authenticate(
    provider: str,
    settings: Settings,
) -> None:
    if provider == "gmail":
        if (
            not settings.gmail_client_id
            or not settings.gmail_client_secret
        ):
            raise ConfigError(
                "GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET "
                "are required for Gmail auth"
            )

        authenticate_gmail(
            settings.gmail_client_id,
            settings.gmail_client_secret,
        )

    else:
        if not settings.microsoft_client_id:
            raise ConfigError(
                "MICROSOFT_CLIENT_ID is required for Microsoft auth"
            )

        authenticate_microsoft(
            settings.microsoft_client_id
        )

    print(
        f"Authenticated with {provider}; "
        "token stored in the OS keychain."
    )


def _parse_scheduled_at(
    value: str,
    *,
    now: datetime | None = None,
) -> datetime:
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}",
        value,
    ):
        raise ConfigError(
            "--at must use YYYY-MM-DD HH:MM"
        )

    try:
        scheduled_at = datetime.strptime(
            value,
            "%Y-%m-%d %H:%M",
        )
    except ValueError as error:
        raise ConfigError(
            "--at must use YYYY-MM-DD HH:MM"
        ) from error

    if scheduled_at <= (
        now or datetime.now()
    ):
        raise ConfigError(
            "--at must be later than the current local time"
        )

    return scheduled_at


def _wait_until_scheduled(
    scheduled_at: datetime,
    *,
    now: Callable[[], datetime] = datetime.now,
    sleep: Callable[[float], None] = time.sleep,
    max_sleep_seconds: float = 60,
) -> None:
    while True:
        remaining = (
            scheduled_at - now()
        ).total_seconds()

        if remaining <= 0:
            return

        sleep(
            min(
                remaining,
                max_sleep_seconds,
            )
        )


def _run_campaign(
    database: CampaignDatabase,
    log_path: Path,
    campaign_id: str,
    settings: Settings,
    args: argparse.Namespace,
    *,
    min_delay: float | None = None,
    max_delay: float | None = None,
) -> None:
    # The provider is stored with the campaign.
    # This allows both "send" and "resume" to use
    # the correct provider without relying on CLI arguments.
    provider = database.campaign_provider(
        campaign_id
    )

    sender, refresh = _provider_sender(
        provider,
        settings,
    )

    engine = SendingEngine(
        database,
        SendLogger(log_path),
        sender,
        _engine_settings(
            settings,
            args,
            min_delay=min_delay,
            max_delay=max_delay,
            provider=provider,
        ),
        refresh=refresh,
    )

    engine.run(campaign_id)


def _send(
    args: argparse.Namespace,
    settings: Settings,
) -> None:
    provider = (
        args.provider
        or settings.provider
    )

    scheduled_at = (
        _parse_scheduled_at(
            args.scheduled_at
        )
        if args.scheduled_at
        else None
    )

    body = Path(
        args.body_file
    ).read_text(
        encoding="utf-8"
    )

    recipients = parse_csv(
        args.csv
    )

    messages = build_messages(
        recipients,
        args.subject,
        body,
    )

    database_path, log_path = _data_paths()

    database = CampaignDatabase(
        database_path
    )

    try:
        campaign_id = database.create_campaign(
            provider,
            messages,
        )

        print(
            f"Campaign {campaign_id} created "
            f"with {len(messages)} recipients."
        )

        if scheduled_at:
            effective_settings = _engine_settings(
                settings,
                args,
                provider=provider,
            )

            database.schedule_campaign(
                campaign_id,
                scheduled_at.isoformat(
                    timespec="minutes"
                ),
                effective_settings.min_delay_seconds,
                effective_settings.max_delay_seconds,
            )

            print(
                f"Campaign {campaign_id} scheduled "
                f"for {args.scheduled_at}."
            )

            print(
                "Waiting for scheduled start..."
            )

            try:
                _wait_until_scheduled(
                    scheduled_at
                )
            except KeyboardInterrupt:
                database.delete_scheduled_campaign(
                    campaign_id
                )

                database.set_campaign_status(
                    campaign_id,
                    "PENDING",
                )

                raise

            if not database.start_scheduled_campaign(
                campaign_id
            ):
                raise ConfigError(
                    "scheduled campaign is no longer "
                    f"available: {campaign_id}"
                )

            database.delete_scheduled_campaign(
                campaign_id
            )

            print(
                f"Starting campaign {campaign_id}..."
            )

        _run_campaign(
            database,
            log_path,
            campaign_id,
            settings,
            args,
        )

    finally:
        database.close()


def _resume(
    args: argparse.Namespace,
    settings: Settings,
) -> None:
    database_path, log_path = _data_paths()

    database = CampaignDatabase(
        database_path
    )

    try:
        campaign_id = (
            args.campaign_id
            or database.resumable_campaign()
        )

        if not campaign_id:
            print(
                "No resumable campaigns found."
            )
            return

        print(
            f"Resuming campaign {campaign_id}."
        )

        _run_campaign(
            database,
            log_path,
            campaign_id,
            settings,
            args,
        )

    finally:
        database.close()


def _status(
    settings: Settings,
) -> None:
    database_path, _ = _data_paths()

    database = CampaignDatabase(
        database_path
    )

    try:
        campaign_id = (
            database.resumable_campaign()
        )

        summary = database.summary(
            campaign_id
        )

        print(
            f"Today's successful sends: "
            f"{database.daily_sent_count()} / "
            f"{settings.daily_limit}"
        )

        print(
            f"Active campaign: "
            f"{campaign_id or 'none'}"
        )

        print(
            f"Pending: "
            f"{summary.get('PENDING', 0) + summary.get('RETRY', 0)}"
        )

        print(
            f"Sent: "
            f"{summary.get('SENT', 0)}"
        )

        print(
            f"Failed: "
            f"{summary.get('FAILED', 0)}"
        )

    finally:
        database.close()


def _log() -> None:
    _, log_path = _data_paths()

    for event in SendLogger(
        log_path
    ).read_events():

        parts = [
            f"[{event['timestamp']}]",
            f"{event['status']:<13}",
            f"{event.get('email') or ''}",
            f"| name: {event.get('name') or ''}",
            f"| provider: {event.get('provider') or ''}",
            f"| campaign: {event['campaign_id']}",
        ]

        if event.get("attempt") is not None:
            parts.append(
                f"| attempt: {event['attempt']}"
            )

        if event.get("error"):
            parts.append(
                f"| error: {event['error']}"
            )

        print(
            " ".join(parts)
        )


def main() -> int:
    parser = build_parser()

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    try:
        settings = load_settings(
            args.config
        )

        if args.command == "auth":
            _authenticate(
                args.provider,
                settings,
            )

        elif args.command == "send":
            _send(
                args,
                settings,
            )

        elif args.command == "resume":
            _resume(
                args,
                settings,
            )

        elif args.command == "status":
            _status(
                settings
            )

        elif args.command == "log":
            _log()

    except (
        ConfigError,
        OSError,
        ValueError,
    ) as error:
        parser.error(
            str(error)
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )