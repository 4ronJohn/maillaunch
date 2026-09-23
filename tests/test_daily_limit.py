from campaign.database import CampaignDatabase
from sender.engine import EngineSettings, SendingEngine
from utils.logger import SendLogger


def test_daily_limit_counts_successful_sends(tmp_path):
    database = CampaignDatabase(tmp_path / "campaign.sqlite")
    campaign_id = database.create_campaign("gmail", [{"email": "a@example.com", "subject": "s", "body": "b"}])
    recipient = database.pending_recipients(campaign_id)[0]
    database.mark_sent(recipient.id)
    assert database.daily_sent_count() == 1
    assert database.summary(campaign_id) == {"SENT": 1}
    database.close()


def test_engine_stops_at_daily_limit_and_logs_remaining_recipients(tmp_path):
    database = CampaignDatabase(tmp_path / "campaign.sqlite")
    campaign_id = database.create_campaign(
        "gmail",
        [
            {"email": "one@example.com", "subject": "s", "body": "b"},
            {"email": "two@example.com", "subject": "s", "body": "b"},
            {"email": "three@example.com", "subject": "s", "body": "b"},
            {"email": "four@example.com", "subject": "s", "body": "b"},
        ],
    )
    logger = SendLogger(tmp_path / "send.jsonl")
    sent = []
    engine = SendingEngine(
        database,
        logger,
        lambda recipient: sent.append(recipient.email),
        EngineSettings(daily_limit=2, min_delay_seconds=0, max_delay_seconds=0),
        sleep=lambda _delay: None,
        random_delay=lambda _minimum, _maximum: 0,
    )

    engine.run(campaign_id)

    assert sent == ["one@example.com", "two@example.com"]
    assert database.summary(campaign_id) == {"PENDING": 2, "SENT": 2}
    assert database.resumable_campaign() == campaign_id
    assert database.connection.execute(
        "SELECT status FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()["status"] == "LIMIT_REACHED"
    events = logger.read_events()
    assert [event["status"] for event in events] == ["SENT", "SENT", "LIMIT_REACHED"]
    database.close()
