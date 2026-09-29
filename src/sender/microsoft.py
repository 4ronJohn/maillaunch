# Microsoft OAuth authentication using Microsoft Graph.
from __future__ import annotations

import requests

from campaign.database import CampaignRecipient
from sender.engine import SendError

# Microsoft Graph send mail endpoint
ENDPOINT = "https://graph.microsoft.com/v1.0/me/sendMail"


class MicrosoftSender:
    def __init__(
        self,
        access_token: str,
        session: requests.Session | None = None,
    ):
        # Store the OAuth access token
        self.access_token = access_token

        # Reuse the provided session or create a new one
        self.session = session or requests.Session()

    @staticmethod
    def payload(recipient: CampaignRecipient) -> dict:
        # Build the Microsoft Graph email payload
        return {
            "message": {
                "subject": recipient.subject,
                "body": {
                    "contentType": "Text",
                    "content": recipient.body,
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": recipient.email,
                        }
                    }
                ],
            },
            "saveToSentItems": True,
        }

    def __call__(self, recipient: CampaignRecipient) -> None:
        # Send the email through Microsoft Graph
        response = self.session.post(
            ENDPOINT,
            headers={
                "Authorization": f"Bearer {self.access_token}",
            },
            json=self.payload(recipient),
            timeout=30,
        )

        # Handle expired or invalid authentication
        if response.status_code == 401:
            raise SendError(
                "Microsoft authentication expired",
                auth_error=True,
            )

        # Handle other Microsoft Graph errors
        if not 200 <= response.status_code < 300:
            raise SendError(
                f"Microsoft Graph HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )