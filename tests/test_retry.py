from campaign.database import CampaignDatabase
from sender.engine import EngineSettings, SendError, SendingEngine
from utils.logger import SendLogger


def test_retry_uses_exponential_backoff_and_succeeds(tmp_path):
    database = CampaignDatabase(tmp_path / "campaign.sqlite")
    campaign_id = database.create_campaign("gmail", [{"email": "a@example.com", "subject": "s", "body": "b"}])
    attempts = []
    sleeps = []

    def provider(_recipient):
        attempts.append(1)
        if len(attempts) < 3:
            raise SendError("temporary failure")

    engine = SendingEngine(
        database,
        SendLogger(tmp_path / "send.jsonl"),
        provider,
        EngineSettings(min_delay_seconds=0, max_delay_seconds=0, retry_attempts=2),
        sleep=sleeps.append,
        random_delay=lambda _minimum, _maximum: 0,
    )
    engine.run(campaign_id)
    assert len(attempts) == 3
    assert sleeps == [0, 1, 2]
    assert database.summary(campaign_id) == {"SENT": 1}
    database.close()


def test_persistent_failure_reaches_final_failed_attempt(tmp_path):
    database = CampaignDatabase(tmp_path / "campaign.sqlite")
    campaign_id = database.create_campaign(
        "gmail", [{"email": "a@example.com", "subject": "s", "body": "b"}]
    )
    logger = SendLogger(tmp_path / "send.jsonl")
    attempts = []
    sleeps = []

    def provider(_recipient):
        attempts.append(1)
        raise SendError("persistent failure")

    engine = SendingEngine(
        database,
        logger,
        provider,
        EngineSettings(min_delay_seconds=0, max_delay_seconds=0, retry_attempts=2),
        sleep=sleeps.append,
        random_delay=lambda _minimum, _maximum: 0,
    )

    engine.run(campaign_id)

    assert len(attempts) == 3
    assert sleeps == [0, 1, 2]
    events = logger.read_events()
    assert [(event["status"], event["attempt"]) for event in events] == [
        ("RETRY", 1),
        ("RETRY", 2),
        ("FAILED", 3),
    ]
    assert database.summary(campaign_id) == {"FAILED": 1}
    database.close()
