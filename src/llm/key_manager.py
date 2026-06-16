"""API key management with encrypted storage and env-var fallback.

Stores LLM API keys in AES-256-GCM encrypted file at
``config/.llm_keys.enc``. Falls back to environment variables
(ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY) when no
encrypted file exists.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from src.llm.base import ProviderName
from src.utils.config import get_project_root
from src.utils.logger import get_logger

logger = get_logger("llm.key_manager")

_ENV_KEY_MAP: dict[ProviderName, str] = {
    ProviderName.ANTHROPIC: "ANTHROPIC_API_KEY",
    ProviderName.OPENAI: "OPENAI_API_KEY",
    ProviderName.GOOGLE: "GOOGLE_API_KEY",
}

_DEFAULT_KEY_FILE = "config/.llm_keys.enc"
_SALT_SIZE = 16
_NONCE_SIZE = 12


@dataclass
class APIKeyEntry:
    """A single API key entry.

    Attributes:
        key: The raw API key string.
        provider: LLM provider this key belongs to.
        label: Human-readable label for the key.
        added_at: ISO timestamp when key was added.
        expires_at: Optional ISO expiration timestamp.
        is_active: Whether the key is currently usable.
        usage_count: Number of times this key has been used.
    """

    key: str
    provider: str
    label: str
    added_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    expires_at: str | None = None
    is_active: bool = True
    usage_count: int = 0


class KeyManager:
    """Manages LLM API keys with encrypted storage.

    Supports AES-256-GCM encrypted key storage with PBKDF2 key
    derivation from ``LLM_ENCRYPTION_KEY`` env var. Falls back
    to raw environment variables when no encrypted file exists.

    Args:
        key_file: Path to encrypted key file (relative to project root).
    """

    def __init__(self, key_file: str = _DEFAULT_KEY_FILE) -> None:
        self._key_file = get_project_root() / key_file
        self._entries: list[APIKeyEntry] = []
        self._round_robin: dict[str, int] = {}
        self._load_keys()

    def _load_keys(self) -> None:
        """Load keys from encrypted file or fall back to env vars."""
        if self._key_file.exists():
            enc_key = os.environ.get("LLM_ENCRYPTION_KEY", "")
            if enc_key:
                try:
                    self._entries = self._decrypt_file(enc_key)
                    logger.info(
                        "Loaded %d keys from encrypted file",
                        len(self._entries),
                    )
                    return
                except Exception as exc:
                    logger.warning(
                        "Failed to decrypt key file: %s. Falling back to env vars.",
                        exc,
                    )

        # Fallback: read from environment variables
        self._entries = []
        for provider, env_var in _ENV_KEY_MAP.items():
            key = os.environ.get(env_var, "")
            if key:
                self._entries.append(
                    APIKeyEntry(
                        key=key,
                        provider=provider.value,
                        label=f"env:{env_var}",
                    )
                )
                logger.info(
                    "Loaded %s key from env var %s",
                    provider.value,
                    env_var,
                )

    def get_key(self, provider: ProviderName) -> str | None:
        """Get an active API key for the provider using round-robin.

        Args:
            provider: The LLM provider to get a key for.

        Returns:
            API key string, or None if no active key exists.
        """
        active_keys = [
            e for e in self._entries if e.provider == provider.value and e.is_active
        ]
        if not active_keys:
            return None

        idx = self._round_robin.get(provider.value, 0)
        entry = active_keys[idx % len(active_keys)]
        self._round_robin[provider.value] = idx + 1
        entry.usage_count += 1
        return entry.key

    def add_key(
        self,
        provider: ProviderName,
        key: str,
        label: str,
        expires_at: str | None = None,
    ) -> APIKeyEntry:
        """Add a new API key.

        Args:
            provider: LLM provider for the key.
            key: The raw API key string.
            label: Human-readable label.
            expires_at: Optional expiration ISO timestamp.

        Returns:
            The newly created APIKeyEntry.
        """
        entry = APIKeyEntry(
            key=key,
            provider=provider.value,
            label=label,
            expires_at=expires_at,
        )
        self._entries.append(entry)
        logger.info("Added %s key: %s", provider.value, label)
        self._save_if_encrypted()
        return entry

    def remove_key(self, provider: ProviderName, label: str) -> bool:
        """Remove an API key by provider and label.

        Args:
            provider: LLM provider.
            label: Key label to remove.

        Returns:
            True if a key was removed, False if not found.
        """
        before = len(self._entries)
        self._entries = [
            e
            for e in self._entries
            if not (e.provider == provider.value and e.label == label)
        ]
        removed = len(self._entries) < before
        if removed:
            logger.info("Removed %s key: %s", provider.value, label)
            self._save_if_encrypted()
        return removed

    def list_keys(self) -> list[dict[str, Any]]:
        """List all keys with masked values.

        Returns:
            List of key info dicts with masked key values.
        """
        result = []
        for e in self._entries:
            info = asdict(e)
            # Mask the key for security
            if len(e.key) > 8:
                info["key"] = e.key[:8] + "***"
            else:
                info["key"] = "***"
            result.append(info)
        return result

    def rotate_key(self, provider: ProviderName, label: str, new_key: str) -> bool:
        """Replace an existing key value.

        Args:
            provider: LLM provider.
            label: Key label to rotate.
            new_key: New API key value.

        Returns:
            True if key was found and rotated, False otherwise.
        """
        for entry in self._entries:
            if entry.provider == provider.value and entry.label == label:
                entry.key = new_key
                entry.usage_count = 0
                logger.info("Rotated %s key: %s", provider.value, label)
                self._save_if_encrypted()
                return True
        return False

    def has_provider(self, provider: ProviderName) -> bool:
        """Check if any active key exists for the provider.

        Args:
            provider: The LLM provider to check.

        Returns:
            True if at least one active key exists.
        """
        return any(e.provider == provider.value and e.is_active for e in self._entries)

    def _save_if_encrypted(self) -> None:
        """Save to encrypted file if encryption key is available."""
        enc_key = os.environ.get("LLM_ENCRYPTION_KEY", "")
        if enc_key:
            self._encrypt_file(enc_key)

    def _encrypt_file(self, password: str) -> None:
        """Encrypt and write key entries to file.

        Args:
            password: Encryption password from LLM_ENCRYPTION_KEY.
        """
        data = json.dumps(
            [asdict(e) for e in self._entries], ensure_ascii=False
        ).encode("utf-8")

        salt = os.urandom(_SALT_SIZE)
        derived_key = _derive_key(password, salt)
        nonce = os.urandom(_NONCE_SIZE)
        aesgcm = AESGCM(derived_key)
        ciphertext = aesgcm.encrypt(nonce, data, None)

        self._key_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._key_file, "wb") as f:
            f.write(salt + nonce + ciphertext)

        logger.info("Saved %d keys to encrypted file", len(self._entries))

    def _decrypt_file(self, password: str) -> list[APIKeyEntry]:
        """Read and decrypt key entries from file.

        Args:
            password: Encryption password from LLM_ENCRYPTION_KEY.

        Returns:
            List of decrypted APIKeyEntry objects.
        """
        with open(self._key_file, "rb") as f:
            raw = f.read()

        salt = raw[:_SALT_SIZE]
        nonce = raw[_SALT_SIZE : _SALT_SIZE + _NONCE_SIZE]
        ciphertext = raw[_SALT_SIZE + _NONCE_SIZE :]

        derived_key = _derive_key(password, salt)
        aesgcm = AESGCM(derived_key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)

        entries_data = json.loads(plaintext.decode("utf-8"))
        return [APIKeyEntry(**entry) for entry in entries_data]


def _derive_key(password: str, salt: bytes) -> bytes:
    """Derive a 256-bit AES key from password using PBKDF2.

    Args:
        password: Password string.
        salt: Random salt bytes.

    Returns:
        32-byte derived key.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100_000,
    )
    return kdf.derive(password.encode("utf-8"))
