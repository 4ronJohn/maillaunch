from __future__ import annotations

import argparse
import os
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
    parser.add_argument("--config", help="Path to a YAML configuration file")
    subparsers = parser.add_subparsers(dest="command")

    auth = subparsers.add_parser("auth", help="Authenticate a provider")
    auth.add_argument("provider", choices=("gmail", "microsoft"))

    send = subparsers.add_parser("send", help="Start a campaign")
    send.add_argument("--provider", choices=("gmail", "microsoft"))
    send.add_argument("--csv", required=True)
    send.add_argument("--subject", required=True)
    send.add_argument("--body-file", required=True)
    send.add_argument("--min-delay", type=float)
    send.add_argument("--max-delay", type=float)

    subparsers.add_parser("status", help="Show campaign status")
    resume = subparsers.add_parser("resume", help="Resume an interrupted campaign")
    resume.add_argument("campaign_id", nargs="?")
    subparsers.add_parser("log", help="Print today's send log")
    return parser


def _data_paths() -> tuple[Path, Path]:
    data_dir = Path(os.getenv("MAILLAUNCH_DATA_DIR", ".maillaunch"))
    database_path = Path(os.getenv("MAILLAUNCH_DB_PATH", data_dir / "campaigns.sqlite3"))
    log_path = Path(os.getenv("MAILLAUNCH_LOG_PATH", data_dir / "send.jsonl"))
    return database_path, log_path


def _engine_settings(settings: Settings, args: argparse.Namespace) -> EngineSettings:
    return EngineSettings(
        daily_limit=settings.daily_limit,
        min_delay_seconds=settings.send.min_delay_seconds if args.min_delay is None else args.min_delay,
        max_delay_seconds=settings.send.max_delay_seconds if args.max_delay is None else args.max_delay,
        retry_attempts=settings.send.retry_attempts,
        retry_failed=settings.send.retry_failed,
    )


def _provider_sender(provider: str, settings: Settings):
    token = load_token(provider)
    if token is None:
        raise ConfigError(f"no {provider} OAuth token found; run 'maillaunch auth {provider}' first")
    if provider == "gmail":
        sender = GmailSender(token.access_token)

        def refresh() -> bool:
            if not settings.gmail_client_id or not settings.gmail_client_secret:
                return False
            refreshed = refresh_gmail(token, settings.gmail_client_id, settings.gmail_client_secret)
            if refreshed is None:
                return False
            sender.access_token = refreshed.access_token
            return True

        return sender, refresh
    sender = MicrosoftSender(token.access_token)

    def refresh() -> bool:
        if not settings.microsoft_client_id:
            return False
        refreshed = refresh_microsoft(token, settings.microsoft_client_id)
        if refreshed is None:
            return False
        sender.access_token = refreshed.access_token
        return True

    return sender, refresh


def _authenticate(provider: str, settings: Settings) -> None:
    if provider == "gmail":
        if not settings.gmail_client_id or not settings.gmail_client_secret:
            raise ConfigError("GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET are required for Gmail auth")
        authenticate_gmail(settings.gmail_client_id, settings.gmail_client_secret)
    else:
        if not settings.microsoft_client_id:
            raise ConfigError("MICROSOFT_CLIENT_ID is required for Microsoft auth")
        authenticate_microsoft(settings.microsoft_client_id)
    print(f"Authenticated with {provider}; token stored in the OS keychain.")


def _send(args: argparse.Namespace, settings: Settings) -> None:
    provider = args.provider or settings.provider
    body = Path(args.body_file).read_text(encoding="utf-8")
    recipients = parse_csv(args.csv)
    messages = build_messages(recipients, args.subject, body)
    database_path, log_path = _data_paths()
    database = CampaignDatabase(database_path)
    try:
        campaign_id = database.create_campaign(provider, messages)
        print(f"Campaign {campaign_id} created with {len(messages)} recipients.")
        sender, refresh = _provider_sender(provider, settings)
        engine = SendingEngine(
            database,
            SendLogger(log_path),
            sender,
            _engine_settings(settings, args),
            refresh=refresh,
        )
        engine.run(campaign_id)
    finally:
        database.close()


def _resume(args: argparse.Namespace, settings: Settings) -> None:
    database_path, log_path = _data_paths()
    database = CampaignDatabase(database_path)
    try:
        campaign_id = args.campaign_id or database.resumable_campaign()
        if not campaign_id:
            print("No resumable campaigns found.")
            return
        provider = database.campaign_provider(campaign_id)
        sender, refresh = _provider_sender(provider, settings)
        engine = SendingEngine(
            database,
            SendLogger(log_path),
            sender,
            _engine_settings(settings, args),
            refresh=refresh,
        )
        print(f"Resuming campaign {campaign_id}.")
        engine.run(campaign_id)
    finally:
        database.close()


def _status(settings: Settings) -> None:
    database_path, _ = _data_paths()
    database = CampaignDatabase(database_path)
    try:
        campaign_id = database.resumable_campaign()
        summary = database.summary(campaign_id)
        print(f"Today's successful sends: {database.daily_sent_count()} / {settings.daily_limit}")
        print(f"Active campaign: {campaign_id or 'none'}")
        print(f"Pending: {summary.get('PENDING', 0) + summary.get('RETRY', 0)}")
        print(f"Sent: {summary.get('SENT', 0)}")
        print(f"Failed: {summary.get('FAILED', 0)}")
    finally:
        database.close()


def _log() -> None:
    _, log_path = _data_paths()
    for event in SendLogger(log_path).read_events():
        print(f"[{event['timestamp']}] {event['status']:<13} {event.get('email') or ''} | campaign: {event['campaign_id']}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return 0
    try:
        settings = load_settings(args.config)
        if args.command == "auth":
            _authenticate(args.provider, settings)
        elif args.command == "send":
            _send(args, settings)
        elif args.command == "resume":
            _resume(args, settings)
        elif args.command == "status":
            _status(settings)
        elif args.command == "log":
            _log()
    except (ConfigError, OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
