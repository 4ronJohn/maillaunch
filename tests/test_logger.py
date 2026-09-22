import json

from utils.logger import SendLogger


def test_structured_log_round_trip(tmp_path):
    logger = SendLogger(tmp_path / "send.jsonl")
    logger.record("SENT", campaign_id="c_1", email="john@example.com", name="John")
    event = json.loads((tmp_path / "send.jsonl").read_text(encoding="utf-8"))
    assert event["status"] == "SENT"
    assert logger.read_events()[0]["campaign_id"] == "c_1"
