from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from uuid import uuid4

import keyring


# Keyring settings for MailLaunch and Microsoft tokens.
SERVICE_NAME = "maillaunch"
MICROSOFT_PROVIDER = "microsoft"
MICROSOFT_ACCESS_KEY = "microsoft:access_token"
MICROSOFT_REFRESH_KEY = "microsoft:refresh_token"
MICROSOFT_METADATA_KEY = "microsoft:metadata"
MICROSOFT_CHUNK_SIZE = 1000


# Stored OAuth token information.
@dataclass
class Token:
    access_token: str
    refresh_token: str | None = None
    expires_at: float | None = None
    account: str | None = None


# Save an OAuth token securely in the system keyring.
def save_token(provider: str, token: Token) -> None:
    provider_key = provider.strip().lower()

    if provider_key == MICROSOFT_PROVIDER:
        _save_microsoft_token(token)
        return

    keyring.set_password(SERVICE_NAME, provider_key, json.dumps(asdict(token)))

    if keyring.get_password(SERVICE_NAME, provider_key) != json.dumps(asdict(token)):
        raise RuntimeError(f"token could not be persisted for provider {provider_key!r}")


# Load an OAuth token from the system keyring.
def load_token(provider: str) -> Token | None:
    provider_key = provider.strip().lower()

    if provider_key == MICROSOFT_PROVIDER:
        return _load_microsoft_token()

    value = keyring.get_password(SERVICE_NAME, provider_key)

    if not value:
        return None

    return Token(**json.loads(value))


# Delete the stored OAuth token.
def delete_token(provider: str) -> None:
    provider_key = provider.strip().lower()

    if provider_key == MICROSOFT_PROVIDER:
        _delete_key(MICROSOFT_METADATA_KEY)

        for prefix in (MICROSOFT_ACCESS_KEY, MICROSOFT_REFRESH_KEY):
            for index in range(10000):
                if not _delete_key(f"{prefix}:{index}"):
                    break

        _delete_key(MICROSOFT_ACCESS_KEY)
        _delete_key(MICROSOFT_REFRESH_KEY)
        _delete_key(MICROSOFT_PROVIDER)
        return

    _delete_key(provider_key)


# Store Microsoft tokens in chunks to support larger token values.
def _save_microsoft_token(token: Token) -> None:
    generation = uuid4().hex
    access_chunks = _chunks(token.access_token)
    refresh_chunks = _chunks(token.refresh_token or "")

    metadata_value = json.dumps(
        {
            "format": "chunked-v1",
            "generation": generation,
            "access_chunk_count": len(access_chunks),
            "refresh_chunk_count": len(refresh_chunks) if token.refresh_token is not None else 0,
            "expires_at": token.expires_at,
            "account": token.account,
            "has_refresh_token": token.refresh_token is not None,
        },
        separators=(",", ":"),
    )

    new_values = {
        **{
            f"{MICROSOFT_ACCESS_KEY}:{index}": chunk
            for index, chunk in enumerate(access_chunks)
        },
        **{
            f"{MICROSOFT_REFRESH_KEY}:{index}": chunk
            for index, chunk in enumerate(refresh_chunks)
        },
        MICROSOFT_METADATA_KEY: metadata_value,
    }

    for key, value in new_values.items():
        keyring.set_password(SERVICE_NAME, key, value)

        if keyring.get_password(SERVICE_NAME, key) != value:
            raise RuntimeError(f"token could not be persisted for provider {MICROSOFT_PROVIDER!r}")

    # Verify that the saved token can be loaded correctly.
    if _load_microsoft_token() != token:
        raise RuntimeError(f"token could not be persisted for provider {MICROSOFT_PROVIDER!r}")

    old_metadata = keyring.get_password(SERVICE_NAME, MICROSOFT_METADATA_KEY)

    # Remove old token chunks that are no longer needed.
    _cleanup_obsolete_microsoft_keys(
        len(access_chunks),
        len(refresh_chunks) if token.refresh_token is not None else 0,
    )


# Load the Microsoft token from the keyring.
def _load_microsoft_token() -> Token | None:
    metadata_value = keyring.get_password(SERVICE_NAME, MICROSOFT_METADATA_KEY)

    if metadata_value is not None:
        metadata = json.loads(metadata_value)

        if metadata.get("format") == "chunked-v1":
            return _load_chunked_microsoft_token(metadata)

        return _load_split_microsoft_token(metadata_value)

    split_access = keyring.get_password(SERVICE_NAME, MICROSOFT_ACCESS_KEY)
    split_refresh = keyring.get_password(SERVICE_NAME, MICROSOFT_REFRESH_KEY)

    if split_access is not None or split_refresh is not None:
        return _load_split_microsoft_token(None)

    # Check whether token chunks exist without their metadata.
    chunk_exists = any(
        keyring.get_password(SERVICE_NAME, f"{prefix}:0") is not None
        for prefix in (MICROSOFT_ACCESS_KEY, MICROSOFT_REFRESH_KEY)
    )

    if chunk_exists:
        raise RuntimeError("Microsoft token chunk metadata is missing; authenticate again")

    # Load the legacy token format if no newer token exists.
    legacy_value = keyring.get_password(SERVICE_NAME, MICROSOFT_PROVIDER)

    if not legacy_value:
        return None

    return Token(**json.loads(legacy_value))


# Rebuild a Microsoft token from its stored chunks.
def _load_chunked_microsoft_token(metadata: dict) -> Token:
    access = _read_chunks(
        MICROSOFT_ACCESS_KEY,
        metadata["access_chunk_count"],
    )

    refresh_count = metadata["refresh_chunk_count"]
    refresh = _read_chunks(
        MICROSOFT_REFRESH_KEY,
        refresh_count,
    ) if refresh_count else ""

    if metadata.get("has_refresh_token") != bool(refresh_count):
        raise RuntimeError("Microsoft token metadata is invalid; authenticate again")

    return Token(
        access_token=access,
        refresh_token=refresh if refresh_count else None,
        expires_at=metadata.get("expires_at"),
        account=metadata.get("account"),
    )


# Load Microsoft tokens stored using the split format.
def _load_split_microsoft_token(metadata_value: str | None) -> Token:
    if metadata_value is None:
        metadata_value = keyring.get_password(
            SERVICE_NAME,
            MICROSOFT_METADATA_KEY,
        )

    if not metadata_value:
        raise RuntimeError("Microsoft token storage is incomplete; authenticate again")

    metadata = json.loads(metadata_value)

    if metadata.get("format") != "split-v1":
        raise RuntimeError("Microsoft token storage is invalid; authenticate again")

    access_value = keyring.get_password(
        SERVICE_NAME,
        MICROSOFT_ACCESS_KEY,
    )
    refresh_value = keyring.get_password(
        SERVICE_NAME,
        MICROSOFT_REFRESH_KEY,
    )

    if not access_value or not refresh_value:
        raise RuntimeError("Microsoft token storage is incomplete; authenticate again")

    access = json.loads(access_value)
    refresh = json.loads(refresh_value)
    generation = metadata.get("generation")

    if (
        not generation
        or access.get("generation") != generation
        or refresh.get("generation") != generation
        or "value" not in access
        or "value" not in refresh
    ):
        raise RuntimeError("Microsoft token storage is invalid; authenticate again")

    return Token(
        access_token=access["value"],
        refresh_token=refresh["value"] if metadata.get("has_refresh_token") else None,
        expires_at=metadata.get("expires_at"),
        account=metadata.get("account"),
    )


# Split a token into keyring-sized chunks.
def _chunks(value: str) -> list[str]:
    return [
        value[index:index + MICROSOFT_CHUNK_SIZE]
        for index in range(0, len(value), MICROSOFT_CHUNK_SIZE)
    ] or [""]


# Read and combine token chunks from the keyring.
def _read_chunks(prefix: str, count: int) -> str:
    if not isinstance(count, int) or count < 1:
        raise RuntimeError("Microsoft token metadata is invalid; authenticate again")

    chunks = []

    for index in range(count):
        value = keyring.get_password(
            SERVICE_NAME,
            f"{prefix}:{index}",
        )

        if value is None:
            raise RuntimeError("Microsoft token chunk is missing; authenticate again")

        chunks.append(value)

    return "".join(chunks)


# Remove old Microsoft token chunks after saving a new token.
def _cleanup_obsolete_microsoft_keys(access_count: int, refresh_count: int) -> None:
    for prefix, count in (
        (MICROSOFT_ACCESS_KEY, access_count),
        (MICROSOFT_REFRESH_KEY, refresh_count),
    ):
        for index in range(count, 10000):
            if not _delete_key(f"{prefix}:{index}"):
                break

    _delete_key(MICROSOFT_ACCESS_KEY)
    _delete_key(MICROSOFT_REFRESH_KEY)
    _delete_key(MICROSOFT_PROVIDER)


# Delete a keyring entry and report whether it existed.
def _delete_key(key: str) -> bool:
    try:
        keyring.delete_password(SERVICE_NAME, key)
    except keyring.errors.PasswordDeleteError:
        return False

    return True