# Gmail OAuth authentication.
from __future__ import annotations
import requests
import base64
from email.message import EmailMessage
from email.policy import SMTP

from campaign.database import CampaignRecipient
from sender.engine import SendError

# Gmail API send mail endpoint
ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


class GmailSender:
    def __init__(
        self,
        access_token: str,
        session: requests.Session | None = None,
    ):
        # Store the Gmail OAuth access token
        self.access_token = access_token
        self.session = session or requests.Session()

    @staticmethod
    def encode_message(recipient: CampaignRecipient) -> str:
        # Build the email message
        message = EmailMessage(policy=SMTP)
        message["To"] = recipient.email
        message["Subject"] = recipient.subject
        message.set_content(recipient.body, charset="utf-8")

        # Encode the message for the Gmail API
        return base64.urlsafe_b64encode(
            message.as_bytes()
        ).decode("ascii").rstrip("=")

    def __call__(self, recipient: CampaignRecipient) -> None:
        # Send the email through the Gmail API
        response = self.session.post(
            ENDPOINT,
            headers={
                "Authorization": f"Bearer {self.access_token}",
            },
            json={
                "raw": self.encode_message(recipient),
            },
            timeout=30,
        )

        # Handle expired Gmail authentication
        if response.status_code == 401:
            raise SendError(
                "Gmail authentication expired",
                auth_error=True,
            )

        # Handle other Gmail API errors
        if not 200 <= response.status_code < 300:
            raise SendError(
                f"Gmail HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )