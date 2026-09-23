from campaign.database import CampaignDatabase
from sender.engine import EngineSettings, SendError, SendingEngine
from utils.logger import SendLogger


def test_processing_timer_and_progress_output(tmp_path, capsys):
    sleeps = []
    database = CampaignDatabase(tmp_path / "campaign.sqlite")
    campaign_id = database.create_campaign(
        "gmail",
        [
            {"email": "first@example.com", "subject": "s", "body": "b"},
            {"email": "second@example.com", "subject": "s", "body": "b"},
        ],
    )
    engine = SendingEngine(
        database,
        SendLogger(tmp_path / "send.jsonl"),
        lambda _recipient: None,
        EngineSettings(min_delay_seconds=0, max_delay_seconds=0),
        sleep=sleeps.append,
        random_delay=lambda _minimum, _maximum: 4.0,
    )

    engine.run(campaign_id)

    output = capsys.readouterr().out
    assert "Sending 1/2: first@example.com" in output
    assert "SENT: first@example.com" in output
    assert "Sending 2/2: second@example.com" in output
    assert "SENT: second@example.com" in output
    assert "Processing..." in output
    assert "\rProcessing..." in output
    assert "Waiting" not in output
    assert sleeps == [4.0, 4.0]
    assert "Total time:" in output
    database.close()


def test_processing_delay_happens_once_before_each_recipient(tmp_path):
    database = CampaignDatabase(tmp_path / "campaign.sqlite")
    campaign_id = database.create_campaign(
        "gmail",
        [
            {"email": "first@example.com", "subject": "s", "body": "b"},
            {"email": "second@example.com", "subject": "s", "body": "b"},
            {"email": "third@example.com", "subject": "s", "body": "b"},
            {"email": "final@example.com", "subject": "s", "body": "b"},
        ],
    )
    events = []

    def random_delay(_minimum, _maximum):
        events.append("random_delay")
        return 4.0

    def provider(recipient):
        events.append(f"send:{recipient.email}")

    engine = SendingEngine(
        database,
        SendLogger(tmp_path / "send.jsonl"),
        provider,
        EngineSettings(min_delay_seconds=0, max_delay_seconds=0),
        sleep=lambda delay: events.append(f"sleep:{delay}"),
        random_delay=random_delay,
    )

    engine.run(campaign_id)

    assert events == [
        "random_delay",
        "sleep:4.0",
        "send:first@example.com",
        "random_delay",
        "sleep:4.0",
        "send:second@example.com",
        "random_delay",
        "sleep:4.0",
        "send:third@example.com",
        "random_delay",
        "sleep:4.0",
        "send:final@example.com",
    ]
    database.close()


def test_processing_and_total_timers_use_controlled_clock(tmp_path, capsys):
    database = CampaignDatabase(tmp_path / "campaign.sqlite")
    campaign_id = database.create_campaign(
        "gmail", [{"email": "first@example.com", "subject": "s", "body": "b"}]
    )
    clock_reads = []

    def clock():
        value = len(clock_reads) / 10
        clock_reads.append(value)
        return value

    def provider(_recipient):
        assert clock_reads

    engine = SendingEngine(
        database,
        SendLogger(tmp_path / "send.jsonl"),
        provider,
        EngineSettings(min_delay_seconds=0, max_delay_seconds=0),
        sleep=lambda _delay: None,
        random_delay=lambda _minimum, _maximum: 0,
        clock=clock,
        timer_interval=0.001,
    )

    engine.run(campaign_id)

    output = capsys.readouterr().out
    timer_values = [
        float(value)
        for value in __import__("re").findall(r"Processing\.\.\. ([0-9.]+)s", output)
    ]
    assert timer_values
    assert timer_values == sorted(timer_values)
    assert output.count("\rProcessing...") == len(timer_values)
    assert output.count("Total time:") == 1
    assert output.rfind("Total time:") > output.rfind("SENT: first@example.com")
    database.close()


def test_keyboard_interrupt_leaves_recipient_pending(tmp_path):
    database = CampaignDatabase(tmp_path / "campaign.sqlite")
    campaign_id = database.create_campaign(
        "gmail", [{"email": "pending@example.com", "subject": "s", "body": "b"}]
    )

    def interrupt(_delay):
        raise KeyboardInterrupt

    engine = SendingEngine(
        database,
        SendLogger(tmp_path / "send.jsonl"),
        lambda _recipient: None,
        EngineSettings(min_delay_seconds=0, max_delay_seconds=0),
        sleep=interrupt,
        random_delay=lambda _minimum, _maximum: 4.0,
    )

    try:
        engine.run(campaign_id)
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("KeyboardInterrupt should propagate")

    assert database.summary(campaign_id) == {"PENDING": 1}
    assert database.resumable_campaign() == campaign_id
    database.close()


def test_authentication_refresh_success_marks_recipient_sent(tmp_path):
    calls = []
    refreshes = []

    def provider(_recipient):
        calls.append(1)
        if len(calls) == 1:
            raise SendError("expired token", auth_error=True)

    database = CampaignDatabase(tmp_path / "campaign.sqlite")
    campaign_id = database.create_campaign(
        "gmail", [{"email": "a@example.com", "subject": "s", "body": "b"}]
    )
    engine = SendingEngine(
        database,
        SendLogger(tmp_path / "send.jsonl"),
        provider,
        EngineSettings(min_delay_seconds=0, max_delay_seconds=0, retry_attempts=1),
        refresh=lambda: refreshes.append(1) or True,
        sleep=lambda _delay: None,
    )

    assert engine._send_recipient(database.pending_recipients(campaign_id)[0]) is True
    assert len(calls) == 2
    assert refreshes == [1]
    assert database.summary(campaign_id) == {"SENT": 1}
    database.close()


def test_authentication_refresh_failure_marks_recipient_failed(tmp_path):
    database = CampaignDatabase(tmp_path / "campaign.sqlite")
    campaign_id = database.create_campaign(
        "gmail", [{"email": "a@example.com", "subject": "s", "body": "b"}]
    )
    logger = SendLogger(tmp_path / "send.jsonl")
    provider_calls = []
    engine = SendingEngine(
        database,
        logger,
        lambda _recipient: (provider_calls.append(1), (_ for _ in ()).throw(SendError("expired", auth_error=True)))[1],
        EngineSettings(min_delay_seconds=0, max_delay_seconds=0, retry_attempts=2),
        refresh=lambda: False,
        sleep=lambda _delay: None,
    )

    assert engine._send_recipient(database.pending_recipients(campaign_id)[0]) is False
    assert len(provider_calls) == 1
    assert database.summary(campaign_id) == {"FAILED": 1}
    assert logger.read_events()[0]["error"] == "authentication refresh failed"
    database.close()


def test_authentication_refresh_on_final_retry_gets_one_more_attempt(tmp_path):
    calls = []
    database = CampaignDatabase(tmp_path / "campaign.sqlite")
    campaign_id = database.create_campaign(
        "gmail", [{"email": "a@example.com", "subject": "s", "body": "b"}]
    )

    def provider(_recipient):
        calls.append(1)
        if len(calls) == 1:
            raise SendError("expired token", auth_error=True)

    engine = SendingEngine(
        database,
        SendLogger(tmp_path / "send.jsonl"),
        provider,
        EngineSettings(min_delay_seconds=0, max_delay_seconds=0, retry_attempts=0),
        refresh=lambda: True,
        sleep=lambda _delay: None,
    )

    assert engine._send_recipient(database.pending_recipients(campaign_id)[0]) is True
    assert len(calls) == 2
    assert database.summary(campaign_id) == {"SENT": 1}
    database.close()