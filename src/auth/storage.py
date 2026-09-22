from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import keyring


SERVICE_NAME = "maillaunch"


@dataclass
class Token:
    access_token: str
    refresh_token: str | None = None
    expires_at: float | None = None
    account: str | None = None


def save_token(provider: str, token: Token) -> None:
    keyring.set_password(SERVICE_NAME, provider, json.dumps(asdict(token)))


def load_token(provider: str) -> Token | None:
    value = keyring.get_password(SERVICE_NAME, provider)
    if not value:
        return None
    return Token(**json.loads(value))


def delete_token(provider: str) -> None:
    try:
        keyring.delete_password(SERVICE_NAME, provider)
    except keyring.errors.PasswordDeleteError:
        pass
