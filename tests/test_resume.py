from campaign.database import CampaignDatabase


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
