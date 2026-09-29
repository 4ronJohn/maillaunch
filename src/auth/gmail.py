from __future__ import annotations

import time
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from auth.storage import Token, save_token

# Gmail API permission required to send emails.
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


# Authenticate with Google and save the Gmail OAuth token.
def authenticate(client_id: str, client_secret: str, credentials_path: str | Path | None = None) -> Token:
    # Build the Google OAuth client configuration.
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    # Load OAuth configuration from a credentials file when provided.
    if credentials_path:
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    else:
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)

    # Open the browser and complete the Google OAuth flow.
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    # Convert Google credentials into the application's token format.
    token = Token(
        access_token=credentials.token,
        refresh_token=credentials.refresh_token,
        expires_at=credentials.expiry.timestamp() if credentials.expiry else time.time() + 3600,
    )

    # Persist the Gmail token in the system keyring.
    save_token("gmail", token)
    return token


# Refresh an expired Gmail OAuth token.
def refresh(token: Token, client_id: str, client_secret: str) -> Token | None:
    # A refresh cannot be performed without a refresh token.
    if not token.refresh_token:
        return None

    # Recreate Google credentials using the stored token information.
    credentials = Credentials(
        token=token.access_token,
        refresh_token=token.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )

    try:
        # Request a new access token from Google.
        credentials.refresh(Request())
    except Exception:
        return None

    # Convert the refreshed Google credentials into the application's token format.
    refreshed = Token(
        access_token=credentials.token,
        refresh_token=credentials.refresh_token or token.refresh_token,
        expires_at=credentials.expiry.timestamp() if credentials.expiry else time.time() + 3600,
        account=token.account,
    )

    # Persist the refreshed Gmail token.
    save_token("gmail", refreshed)
    return refreshed