from campaign.database import CampaignDatabase


def test_daily_limit_counts_successful_sends(tmp_path):
    database = CampaignDatabase(tmp_path / "campaign.sqlite")
    campaign_id = database.create_campaign("gmail", [{"email": "a@example.com", "subject": "s", "body": "b"}])
    recipient = database.pending_recipients(campaign_id)[0]
    database.mark_sent(recipient.id)
    assert database.daily_sent_count() == 1
    assert database.summary(campaign_id) == {"SENT": 1}
    database.close()
