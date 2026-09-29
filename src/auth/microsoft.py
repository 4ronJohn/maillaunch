from __future__ import annotations

import json
import time

import msal

from auth.storage import Token, save_token

# Microsoft Graph permissions required for authentication and sending email.
SCOPES = ["User.Read", "Mail.Send"]


# Authenticate with Microsoft and save the OAuth token.
def authenticate(client_id: str) -> Token:
    # Create the Microsoft public client application.
    app = msal.PublicClientApplication(
        client_id,
        authority="https://login.microsoftonline.com/common",
    )

    # Open the browser and complete the Microsoft OAuth flow.
    result = app.acquire_token_interactive(scopes=SCOPES)

    # Stop if Microsoft did not return an access token.
    if "access_token" not in result:
        raise RuntimeError(result.get("error_description", "Microsoft authentication failed"))

    # Convert the Microsoft response into the application's token format.
    token = Token(
        access_token=result["access_token"],
        refresh_token=result.get("refresh_token"),
        expires_at=time.time() + int(result.get("expires_in", 3600)),
        account=json.dumps(result.get("id_token_claims", {}).get("preferred_username")),
    )

    # Persist the Microsoft token in the system keyring.
    save_token("microsoft", token)
    return token


# Refresh an expired Microsoft OAuth token.
def refresh(token: Token, client_id: str) -> Token | None:
    # A refresh cannot be performed without a refresh token.
    if not token.refresh_token:
        return None

    # Create the Microsoft public client application for token refresh.
    app = msal.PublicClientApplication(client_id, authority="https://login.microsoftonline.com/common")

    # Request a new access token using the stored refresh token.
    result = app.acquire_token_by_refresh_token(token.refresh_token, scopes=SCOPES)

    # Return None if Microsoft did not return a new access token.
    if "access_token" not in result:
        return None

    # Convert the refreshed Microsoft response into the application's token format.
    refreshed = Token(
        access_token=result["access_token"],
        refresh_token=result.get("refresh_token", token.refresh_token),
        expires_at=time.time() + int(result.get("expires_in", 3600)),
        account=token.account,
    )

    # Persist the refreshed Microsoft token.
    save_token("microsoft", refreshed)
    return refreshed