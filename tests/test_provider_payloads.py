from campaign.database import CampaignRecipient
from sender.gmail import GmailSender
from sender.microsoft import MicrosoftSender


RECIPIENT = CampaignRecipient(1, "c_1", "john@example.com", "John", "Hello", "Body", "PENDING", 0, None)


def test_gmail_payload_is_urlsafe_base64():
    encoded = GmailSender.encode_message(RECIPIENT)
    assert "+" not in encoded and "/" not in encoded
    assert len(encoded) > 20


def test_graph_payload():
    payload = MicrosoftSender.payload(RECIPIENT)
    assert payload["message"]["toRecipients"][0]["emailAddress"]["address"] == RECIPIENT.email
    assert payload["message"]["subject"] == "Hello"
