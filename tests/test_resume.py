from campaign.database import CampaignDatabase
from sender.engine import EngineSettings, SendingEngine
from utils.logger import SendLogger


def test_pending_query_never_returns_sent_recipients(tmp_path):
    database = CampaignDatabase(tmp_path / "campaign.sqlite")
    campaign_id = database.create_campaign(
        "gmail",
        [
            {"email": "sent@example.com", "subject": "s", "body": "b"},
            {"email": "pending@example.com", "subject": "s", "body": "b"},
        ],
    )
    first = database.pending_recipients(campaign_id)[0]
    database.mark_sent(first.id)
    pending = database.pending_recipients(campaign_id)
    assert [recipient.email for recipient in pending] == ["pending@example.com"]
    database.close()


def test_interrupted_campaign_resumes_only_pending_recipients(tmp_path):
    database = CampaignDatabase(tmp_path / "campaign.sqlite")
    campaign_id = database.create_campaign(
        "gmail",
        [
            {"email": "first@example.com", "subject": "s", "body": "b"},
            {"email": "second@example.com", "subject": "s", "body": "b"},
            {"email": "third@example.com", "subject": "s", "body": "b"},
        ],
    )
    first_run_calls = []

    def interrupting_provider(recipient):
        first_run_calls.append(recipient.email)
        if recipient.email == "second@example.com":
            raise KeyboardInterrupt

    engine = SendingEngine(
        database,
        SendLogger(tmp_path / "send.jsonl"),
        interrupting_provider,
        EngineSettings(min_delay_seconds=0, max_delay_seconds=0, retry_attempts=0),
        sleep=lambda _delay: None,
        random_delay=lambda _minimum, _maximum: 0,
    )

    try:
        engine.run(campaign_id)
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("KeyboardInterrupt should propagate")

    assert first_run_calls == ["first@example.com", "second@example.com"]
    assert database.summary(campaign_id) == {"PENDING": 2, "SENT": 1}
    assert database.resumable_campaign() == campaign_id

    resumed_calls = []
    resumed_engine = SendingEngine(
        database,
        SendLogger(tmp_path / "send.jsonl"),
        lambda recipient: resumed_calls.append(recipient.email),
        EngineSettings(min_delay_seconds=0, max_delay_seconds=0),
        sleep=lambda _delay: None,
        random_delay=lambda _minimum, _maximum: 0,
    )

    resumed_engine.run(campaign_id)

    assert resumed_calls == ["second@example.com", "third@example.com"]
    assert "first@example.com" not in resumed_calls
    assert database.summary(campaign_id) == {"SENT": 3}
    database.close()
