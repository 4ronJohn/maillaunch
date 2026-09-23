import argparse
from datetime import datetime, timedelta

import pytest

import main
from campaign.database import CampaignDatabase
from utils.config import ConfigError, SendSettings, Settings


def _settings() -> Settings:
    return Settings(send=SendSettings(min_delay_seconds=0, max_delay_seconds=0))


def _send_args(tmp_path, scheduled_at=None):
    csv_path = tmp_path / "recipients.csv"
    csv_path.write_text("email\na@example.com\n", encoding="utf-8")
    body_path = tmp_path / "body.txt"
    body_path.write_text("Hello", encoding="utf-8")
    return argparse.Namespace(
        provider="gmail",
        csv=str(csv_path),
        subject="Subject",
        body_file=str(body_path),
        min_delay=0,
        max_delay=0,
        scheduled_at=scheduled_at,
        config=None,
    )


def test_immediate_send_still_runs_campaign(tmp_path, monkeypatch):
    database_path = tmp_path / "campaign.sqlite"
    monkeypatch.setenv("MAILLAUNCH_DB_PATH", str(database_path))
    calls = []
    monkeypatch.setattr(main, "_run_campaign", lambda *args, **kwargs: calls.append(args[2]))

    main._send(_send_args(tmp_path), _settings())

    assert len(calls) == 1
    database = CampaignDatabase(database_path)
    assert database.summary(calls[0]) == {"PENDING": 1}
    database.close()


def test_wait_helper_uses_bounded_injected_sleep():
    current = [datetime(2026, 9, 23, 13, 59)]
    sleeps = []
    scheduled_at = current[0] + timedelta(seconds=125)

    def sleep(seconds):
        sleeps.append(seconds)
        current[0] += timedelta(seconds=seconds)

    main._wait_until_scheduled(
        scheduled_at,
        now=lambda: current[0],
        sleep=sleep,
        max_sleep_seconds=60,
    )

    assert sleeps == [60, 60, 5]
    assert current[0] == scheduled_at


def test_scheduled_send_waits_before_running_engine_and_persists_metadata(
    tmp_path, monkeypatch, capsys
):
    database_path = tmp_path / "campaign.sqlite"
    monkeypatch.setenv("MAILLAUNCH_DB_PATH", str(database_path))
    order = []
    campaign_ids = []

    def wait(_scheduled_at):
        database = CampaignDatabase(database_path)
        assert database.resumable_campaign() is None
        record = database.connection.execute("SELECT status FROM campaigns").fetchone()
        assert record["status"] == "SCHEDULED"
        order.append("wait")
        database.close()

    def run_campaign(database, _log_path, campaign_id, _settings, _args):
        order.append("run")
        campaign_ids.append(campaign_id)
        assert database.scheduled_campaign(campaign_id) is None

    monkeypatch.setattr(main, "_wait_until_scheduled", wait)
    monkeypatch.setattr(main, "_run_campaign", run_campaign)

    main._send(_send_args(tmp_path, "2099-01-02 03:04"), _settings())

    assert order == ["wait", "run"]
    assert len(campaign_ids) == 1
    database = CampaignDatabase(database_path)
    assert database.summary(campaign_ids[0]) == {"PENDING": 1}
    assert database.resumable_campaign() == campaign_ids[0]
    database.close()
    output = capsys.readouterr().out
    assert "scheduled for 2099-01-02 03:04" in output
    assert "Waiting for scheduled start..." in output
    assert "Starting campaign" in output


def test_scheduled_send_runs_existing_engine_after_wait(tmp_path, monkeypatch):
    database_path = tmp_path / "campaign.sqlite"
    log_path = tmp_path / "send.jsonl"
    monkeypatch.setenv("MAILLAUNCH_DB_PATH", str(database_path))
    monkeypatch.setenv("MAILLAUNCH_LOG_PATH", str(log_path))
    sent = []
    monkeypatch.setattr(main, "_wait_until_scheduled", lambda _scheduled_at: None)
    monkeypatch.setattr(
        main,
        "_provider_sender",
        lambda *_args: (lambda recipient: sent.append(recipient.email), lambda: False),
    )

    main._send(_send_args(tmp_path, "2099-01-02 03:04"), _settings())

    assert sent == ["a@example.com"]
    database = CampaignDatabase(database_path)
    assert database.summary() == {"SENT": 1}
    assert database.connection.execute(
        "SELECT COUNT(*) FROM scheduled_campaigns"
    ).fetchone()[0] == 0
    database.close()


def test_ctrl_c_during_wait_keeps_campaign_pending_without_sending(tmp_path, monkeypatch):
    database_path = tmp_path / "campaign.sqlite"
    monkeypatch.setenv("MAILLAUNCH_DB_PATH", str(database_path))
    run_calls = []
    monkeypatch.setattr(
        main,
        "_wait_until_scheduled",
        lambda _scheduled_at: (_ for _ in ()).throw(KeyboardInterrupt),
    )
    monkeypatch.setattr(main, "_run_campaign", lambda *args, **kwargs: run_calls.append(True))

    with pytest.raises(KeyboardInterrupt):
        main._send(_send_args(tmp_path, "2099-01-02 03:04"), _settings())

    assert run_calls == []
    database = CampaignDatabase(database_path)
    campaign_id = database.resumable_campaign()
    assert campaign_id is not None
    assert database.summary(campaign_id) == {"PENDING": 1}
    assert database.scheduled_campaign(campaign_id) is None
    database.close()


@pytest.mark.parametrize(
    "value",
    ["bad", "2099-02-30 09:00", "2099-01-02 9:00"],
)
def test_invalid_schedule_values_are_rejected(value):
    with pytest.raises(ConfigError, match="--at"):
        main._parse_scheduled_at(value, now=datetime(2026, 9, 23, 8, 0))


def test_past_schedule_is_rejected_before_campaign_creation():
    with pytest.raises(ConfigError, match="later than"):
        main._parse_scheduled_at(
            "2026-09-23 07:59", now=datetime(2026, 9, 23, 8, 0)
        )