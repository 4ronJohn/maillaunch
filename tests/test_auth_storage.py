import json

import keyring as keyring_module
import pytest

from auth import microsoft
from auth.storage import (
    MICROSOFT_ACCESS_KEY,
    MICROSOFT_CHUNK_SIZE,
    MICROSOFT_METADATA_KEY,
    MICROSOFT_REFRESH_KEY,
    SERVICE_NAME,
    Token,
    load_token,
    save_token,
)


class MemoryKeyring:
    def __init__(self):
        self.values = {}

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def get_password(self, service, username):
        return self.values.get((service, username))

    def delete_password(self, service, username):
        if (service, username) not in self.values:
            raise keyring_module.errors.PasswordDeleteError
        del self.values[(service, username)]


def test_microsoft_authentication_saves_and_loads_microsoft_token(monkeypatch):
    keyring = MemoryKeyring()
    monkeypatch.setattr("auth.storage.keyring.set_password", keyring.set_password)
    monkeypatch.setattr("auth.storage.keyring.get_password", keyring.get_password)

    class FakeApplication:
        def __init__(self, client_id, authority):
            assert client_id == "client-id"
            assert authority.endswith("/common")

        def acquire_token_interactive(self, scopes):
            assert scopes == microsoft.SCOPES
            return {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "expires_in": 3600,
                "id_token_claims": {"preferred_username": "user@example.com"},
            }

    monkeypatch.setattr(microsoft.msal, "PublicClientApplication", FakeApplication)

    token = microsoft.authenticate("client-id")
    loaded = load_token("MICROSOFT")

    assert token == loaded
    assert (SERVICE_NAME, f"{MICROSOFT_ACCESS_KEY}:0") in keyring.values
    assert (SERVICE_NAME, f"{MICROSOFT_REFRESH_KEY}:0") in keyring.values
    assert (SERVICE_NAME, MICROSOFT_METADATA_KEY) in keyring.values
    assert (SERVICE_NAME, "microsoft") not in keyring.values


def test_save_token_normalizes_provider_key(monkeypatch):
    keyring = MemoryKeyring()
    monkeypatch.setattr("auth.storage.keyring.set_password", keyring.set_password)
    monkeypatch.setattr("auth.storage.keyring.get_password", keyring.get_password)

    save_token(" Microsoft ", Token("access-token"))

    assert load_token("microsoft").access_token == "access-token"


def test_gmail_keeps_legacy_single_entry_storage(monkeypatch):
    keyring = MemoryKeyring()
    monkeypatch.setattr("auth.storage.keyring.set_password", keyring.set_password)
    monkeypatch.setattr("auth.storage.keyring.get_password", keyring.get_password)
    token = Token("gmail-access", "gmail-refresh", 123.0, "gmail@example.com")

    save_token("gmail", token)

    assert (SERVICE_NAME, "gmail") in keyring.values
    assert load_token("gmail") == token


def test_microsoft_loads_legacy_json_when_split_entries_are_absent(monkeypatch):
    keyring = MemoryKeyring()
    monkeypatch.setattr("auth.storage.keyring.get_password", keyring.get_password)
    token = Token("legacy-access", "legacy-refresh", 123.0, "user@example.com")
    keyring.values[(SERVICE_NAME, "microsoft")] = json.dumps(token.__dict__)

    assert load_token("microsoft") == token


def test_microsoft_without_refresh_token_round_trips(monkeypatch):
    keyring = MemoryKeyring()
    monkeypatch.setattr("auth.storage.keyring.set_password", keyring.set_password)
    monkeypatch.setattr("auth.storage.keyring.get_password", keyring.get_password)
    token = Token("access-only", None, 123.0, "user@example.com")

    save_token("microsoft", token)

    assert load_token("microsoft") == token


def test_1544_character_access_token_is_chunked(monkeypatch):
    keyring = MemoryKeyring()
    monkeypatch.setattr("auth.storage.keyring.set_password", keyring.set_password)
    monkeypatch.setattr("auth.storage.keyring.get_password", keyring.get_password)
    token = Token("a" * 1544, "refresh", 123.0, "user@example.com")

    save_token("microsoft", token)

    metadata = json.loads(keyring.values[(SERVICE_NAME, MICROSOFT_METADATA_KEY)])
    assert metadata["format"] == "chunked-v1"
    assert metadata["access_chunk_count"] == 2
    assert len(keyring.values[(SERVICE_NAME, f"{MICROSOFT_ACCESS_KEY}:0")]) == MICROSOFT_CHUNK_SIZE
    assert len(keyring.values[(SERVICE_NAME, f"{MICROSOFT_ACCESS_KEY}:1")]) == 544
    assert load_token("microsoft") == token


def test_large_refresh_token_is_chunked_and_round_trips(monkeypatch):
    keyring = MemoryKeyring()
    monkeypatch.setattr("auth.storage.keyring.set_password", keyring.set_password)
    monkeypatch.setattr("auth.storage.keyring.get_password", keyring.get_password)
    token = Token("access", "r" * 2345, 123.0, "user@example.com")

    save_token("microsoft", token)

    metadata = json.loads(keyring.values[(SERVICE_NAME, MICROSOFT_METADATA_KEY)])
    assert metadata["refresh_chunk_count"] == 3
    assert load_token("microsoft") == token


def test_missing_chunk_raises_clear_error(monkeypatch):
    keyring = MemoryKeyring()
    monkeypatch.setattr("auth.storage.keyring.get_password", keyring.get_password)
    keyring.values[(SERVICE_NAME, MICROSOFT_METADATA_KEY)] = json.dumps(
        {
            "format": "chunked-v1",
            "generation": "generation",
            "access_chunk_count": 2,
            "refresh_chunk_count": 0,
            "expires_at": 123.0,
            "account": "user@example.com",
            "has_refresh_token": False,
        }
    )
    keyring.values[(SERVICE_NAME, f"{MICROSOFT_ACCESS_KEY}:0")] = "access"

    with pytest.raises(RuntimeError, match="chunk is missing"):
        load_token("microsoft")


def test_split_v1_fallback_still_loads(monkeypatch):
    keyring = MemoryKeyring()
    monkeypatch.setattr("auth.storage.keyring.get_password", keyring.get_password)
    token = Token("split-access", "split-refresh", 123.0, "user@example.com")
    keyring.values[(SERVICE_NAME, MICROSOFT_ACCESS_KEY)] = json.dumps(
        {"generation": "generation", "value": token.access_token}
    )
    keyring.values[(SERVICE_NAME, MICROSOFT_REFRESH_KEY)] = json.dumps(
        {"generation": "generation", "value": token.refresh_token}
    )
    keyring.values[(SERVICE_NAME, MICROSOFT_METADATA_KEY)] = json.dumps(
        {
            "format": "split-v1",
            "generation": "generation",
            "expires_at": token.expires_at,
            "account": token.account,
            "has_refresh_token": True,
        }
    )

    assert load_token("microsoft") == token


def test_stale_chunks_are_removed_after_replacement(monkeypatch):
    keyring = MemoryKeyring()
    monkeypatch.setattr("auth.storage.keyring.set_password", keyring.set_password)
    monkeypatch.setattr("auth.storage.keyring.get_password", keyring.get_password)
    monkeypatch.setattr("auth.storage.keyring.delete_password", keyring.delete_password)
    old_token = Token("a" * 2200, "r" * 2200, 123.0, "user@example.com")
    save_token("microsoft", old_token)
    new_token = Token("new-access", "new-refresh", 456.0, "user@example.com")

    save_token("microsoft", new_token)

    assert (SERVICE_NAME, f"{MICROSOFT_ACCESS_KEY}:1") not in keyring.values
    assert (SERVICE_NAME, f"{MICROSOFT_REFRESH_KEY}:1") not in keyring.values
    assert load_token("microsoft") == new_token


def test_microsoft_refresh_saves_replacement_token(monkeypatch):
    keyring = MemoryKeyring()
    monkeypatch.setattr("auth.storage.keyring.set_password", keyring.set_password)
    monkeypatch.setattr("auth.storage.keyring.get_password", keyring.get_password)

    class FakeApplication:
        def __init__(self, client_id, authority):
            assert client_id == "client-id"
            assert authority.endswith("/common")

        def acquire_token_by_refresh_token(self, refresh_token, scopes):
            assert refresh_token == "old-refresh-token"
            assert scopes == microsoft.SCOPES
            return {
                "access_token": "new-access-token",
                "refresh_token": "new-refresh-token",
                "expires_in": 3600,
            }

    monkeypatch.setattr(microsoft.msal, "PublicClientApplication", FakeApplication)
    original = Token(
        "old-access-token",
        refresh_token="old-refresh-token",
        account="user@example.com",
    )

    refreshed = microsoft.refresh(original, "client-id")

    assert refreshed is not None
    assert refreshed.access_token == "new-access-token"
    assert refreshed.refresh_token == "new-refresh-token"
    assert load_token("microsoft") == refreshed