"""Unit tests for src/llm/key_manager.py — KeyManager.

Tests encrypted storage, env var fallback, add/remove/rotate/list keys,
and round-robin key selection.
"""

import os
from unittest.mock import patch


from src.llm.base import ProviderName
from src.llm.key_manager import APIKeyEntry, KeyManager, _derive_key


class TestKeyManagerEnvFallback:
    """Tests for env-var fallback when no encrypted file exists."""

    @patch.dict(
        os.environ,
        {
            "ANTHROPIC_API_KEY": "sk-ant-test123456",
            "OPENAI_API_KEY": "sk-oai-test123456",
        },
        clear=False,
    )
    def test_loads_from_env_vars(self, tmp_path):
        km = KeyManager(key_file=str(tmp_path / "nonexistent.enc"))
        keys = km.list_keys()
        providers = {k["provider"] for k in keys}
        assert "anthropic" in providers
        assert "openai" in providers

    @patch.dict(
        os.environ,
        {"ANTHROPIC_API_KEY": "sk-ant-test123456"},
        clear=False,
    )
    def test_get_key_returns_env_key(self, tmp_path):
        km = KeyManager(key_file=str(tmp_path / "nonexistent.enc"))
        key = km.get_key(ProviderName.ANTHROPIC)
        assert key == "sk-ant-test123456"

    @patch.dict(os.environ, {}, clear=True)
    def test_no_keys_returns_none(self, tmp_path):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("GOOGLE_API_KEY", None)
        os.environ.pop("LLM_ENCRYPTION_KEY", None)
        km = KeyManager(key_file=str(tmp_path / "nonexistent.enc"))
        assert km.get_key(ProviderName.ANTHROPIC) is None

    @patch.dict(
        os.environ,
        {"ANTHROPIC_API_KEY": "sk-ant-test123456"},
        clear=False,
    )
    def test_list_keys_masks_values(self, tmp_path):
        km = KeyManager(key_file=str(tmp_path / "nonexistent.enc"))
        keys = km.list_keys()
        for k in keys:
            assert "***" in k["key"]
            assert len(k["key"]) <= 11  # max 8 chars + ***


class TestKeyManagerOperations:
    """Tests for add/remove/rotate operations."""

    @patch.dict(os.environ, {}, clear=True)
    def test_add_key(self, tmp_path):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("GOOGLE_API_KEY", None)
        os.environ.pop("LLM_ENCRYPTION_KEY", None)
        km = KeyManager(key_file=str(tmp_path / "keys.enc"))
        entry = km.add_key(ProviderName.OPENAI, "sk-openai-new", "test-key")
        assert entry.provider == "openai"
        assert entry.label == "test-key"

        key = km.get_key(ProviderName.OPENAI)
        assert key == "sk-openai-new"

    @patch.dict(os.environ, {}, clear=True)
    def test_remove_key(self, tmp_path):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("GOOGLE_API_KEY", None)
        os.environ.pop("LLM_ENCRYPTION_KEY", None)
        km = KeyManager(key_file=str(tmp_path / "keys.enc"))
        km.add_key(ProviderName.OPENAI, "sk-openai-1", "key-1")
        assert km.remove_key(ProviderName.OPENAI, "key-1") is True
        assert km.get_key(ProviderName.OPENAI) is None

    @patch.dict(os.environ, {}, clear=True)
    def test_remove_nonexistent_returns_false(self, tmp_path):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("GOOGLE_API_KEY", None)
        os.environ.pop("LLM_ENCRYPTION_KEY", None)
        km = KeyManager(key_file=str(tmp_path / "keys.enc"))
        assert km.remove_key(ProviderName.OPENAI, "nope") is False

    @patch.dict(os.environ, {}, clear=True)
    def test_rotate_key(self, tmp_path):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("GOOGLE_API_KEY", None)
        os.environ.pop("LLM_ENCRYPTION_KEY", None)
        km = KeyManager(key_file=str(tmp_path / "keys.enc"))
        km.add_key(ProviderName.GOOGLE, "old-key-12345678", "g-key")
        assert km.rotate_key(ProviderName.GOOGLE, "g-key", "new-key-12345678")
        assert km.get_key(ProviderName.GOOGLE) == "new-key-12345678"

    @patch.dict(os.environ, {}, clear=True)
    def test_round_robin(self, tmp_path):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("GOOGLE_API_KEY", None)
        os.environ.pop("LLM_ENCRYPTION_KEY", None)
        km = KeyManager(key_file=str(tmp_path / "keys.enc"))
        km.add_key(ProviderName.ANTHROPIC, "key-a", "a")
        km.add_key(ProviderName.ANTHROPIC, "key-b", "b")

        first = km.get_key(ProviderName.ANTHROPIC)
        second = km.get_key(ProviderName.ANTHROPIC)
        assert first == "key-a"
        assert second == "key-b"

    @patch.dict(os.environ, {}, clear=True)
    def test_has_provider(self, tmp_path):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("GOOGLE_API_KEY", None)
        os.environ.pop("LLM_ENCRYPTION_KEY", None)
        km = KeyManager(key_file=str(tmp_path / "keys.enc"))
        assert km.has_provider(ProviderName.ANTHROPIC) is False
        km.add_key(ProviderName.ANTHROPIC, "key-x", "x")
        assert km.has_provider(ProviderName.ANTHROPIC) is True


class TestKeyManagerEncryption:
    """Tests for encrypted storage."""

    @patch.dict(
        os.environ,
        {"LLM_ENCRYPTION_KEY": "test-password-123"},
        clear=False,
    )
    def test_encrypt_decrypt_roundtrip(self, tmp_path):
        key_file = str(tmp_path / "test_keys.enc")
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("GOOGLE_API_KEY", None)

        km1 = KeyManager(key_file=key_file)
        km1.add_key(ProviderName.ANTHROPIC, "sk-secret-12345678", "prod")

        # Load again from file
        km2 = KeyManager(key_file=key_file)
        key = km2.get_key(ProviderName.ANTHROPIC)
        assert key == "sk-secret-12345678"

    def test_derive_key_deterministic(self):
        salt = b"\x00" * 16
        key1 = _derive_key("password", salt)
        key2 = _derive_key("password", salt)
        assert key1 == key2
        assert len(key1) == 32

    def test_derive_key_different_salts(self):
        key1 = _derive_key("password", b"\x00" * 16)
        key2 = _derive_key("password", b"\x01" * 16)
        assert key1 != key2


class TestAPIKeyEntry:
    """Tests for APIKeyEntry dataclass."""

    def test_defaults(self):
        entry = APIKeyEntry(key="sk-test", provider="anthropic", label="test")
        assert entry.is_active is True
        assert entry.usage_count == 0
        assert entry.expires_at is None
        assert entry.added_at  # auto-generated
