from __future__ import annotations

import json
import time

import msal

from auth.storage import Token, save_token

SCOPES = ["User.Read", "Mail.Send"]


def authenticate(client_id: str) -> Token:
    app = msal.PublicClientApplication(
        client_id,
        authority="https://login.microsoftonline.com/common",
    )
    result = app.acquire_token_interactive(scopes=SCOPES)
    if "access_token" not in result:
        raise RuntimeError(result.get("error_description", "Microsoft authentication failed"))
    token = Token(
        access_token=result["access_token"],
        refresh_token=result.get("refresh_token"),
        expires_at=time.time() + int(result.get("expires_in", 3600)),
        account=json.dumps(result.get("id_token_claims", {}).get("preferred_username")),
    )
    save_token("microsoft", token)
    return token


def refresh(token: Token, client_id: str) -> Token | None:
    if not token.refresh_token:
        return None
    app = msal.PublicClientApplication(client_id, authority="https://login.microsoftonline.com/common")
    result = app.acquire_token_by_refresh_token(token.refresh_token, scopes=SCOPES)
    if "access_token" not in result:
        return None
    refreshed = Token(
        access_token=result["access_token"],
        refresh_token=result.get("refresh_token", token.refresh_token),
        expires_at=time.time() + int(result.get("expires_in", 3600)),
        account=token.account,
    )
    save_token("microsoft", refreshed)
    return refreshed
