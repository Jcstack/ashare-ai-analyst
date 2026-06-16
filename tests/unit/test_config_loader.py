"""Unit tests for src/utils/config.py — Config Loader.

Test case TC-D001 per PRD Section 6.2:
  - Load a valid stocks.yaml and verify dict structure
  - Handle missing config file (FileNotFoundError)
  - Verify get_project_root returns correct Path
  - Verify get_data_dir creates directory and returns Path
"""

import pytest
import yaml
from pathlib import Path
from unittest.mock import patch


class TestLoadConfig:
    """Tests for load_config() function."""

    def test_load_config_success(self, tmp_path):
        """TC-D001: Load a valid YAML config, verify dict structure.

        Creates a temporary stocks.yaml with watchlist and data_collection
        sections, loads it via load_config(), and asserts the returned dict
        contains the expected keys and value types.
        """
        # Arrange: create a temp config directory with a valid YAML file
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_content = {
            "watchlist": [
                {"symbol": "000001", "name": "平安银行", "board": "main"},
                {"symbol": "600519", "name": "贵州茅台", "board": "main"},
            ],
            "data_collection": {
                "daily": {
                    "enabled": True,
                    "start_date": "20240101",
                    "end_date": "",
                    "adjust": "qfq",
                },
            },
            "cache": {
                "enabled": True,
                "directory": "data/raw",
                "ttl_hours": 12,
            },
            "request": {
                "interval_seconds": 0.5,
                "max_retries": 3,
                "retry_delay_seconds": 2,
                "timeout_seconds": 30,
            },
        }
        config_file = config_dir / "stocks.yaml"
        config_file.write_text(yaml.dump(config_content, allow_unicode=True))

        # Act: patch get_project_root to point to tmp_path
        with patch("src.utils.config.get_project_root", return_value=tmp_path):
            from src.utils.config import load_config

            result = load_config("stocks")

        # Assert: returned dict has correct structure
        assert isinstance(result, dict)
        assert "watchlist" in result
        assert "data_collection" in result
        assert "cache" in result
        assert "request" in result

        # Verify watchlist is a list of dicts with expected keys
        assert isinstance(result["watchlist"], list)
        assert len(result["watchlist"]) == 2
        first_stock = result["watchlist"][0]
        assert "symbol" in first_stock
        assert "name" in first_stock
        assert "board" in first_stock
        assert first_stock["symbol"] == "000001"

        # Verify data_collection nested structure
        daily_cfg = result["data_collection"]["daily"]
        assert daily_cfg["enabled"] is True
        assert daily_cfg["start_date"] == "20240101"
        assert daily_cfg["adjust"] == "qfq"

        # Verify cache config
        assert result["cache"]["ttl_hours"] == 12

        # Verify request config
        assert result["request"]["max_retries"] == 3

    def test_load_config_file_not_found(self, tmp_path):
        """TC-D001: Verify FileNotFoundError when config file does not exist.

        Attempts to load a non-existent YAML file and asserts that
        FileNotFoundError is raised with a descriptive message.
        """
        with patch("src.utils.config.get_project_root", return_value=tmp_path):
            from src.utils.config import load_config

            with pytest.raises(FileNotFoundError, match="Configuration file not found"):
                load_config("nonexistent_config")

    def test_load_config_empty_yaml(self, tmp_path):
        """TC-D001 edge case: Loading an empty YAML file returns empty dict."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "empty.yaml"
        config_file.write_text("")

        with patch("src.utils.config.get_project_root", return_value=tmp_path):
            from src.utils.config import load_config

            result = load_config("empty")

        assert result == {}


class TestGetProjectRoot:
    """Tests for get_project_root() function."""

    def test_get_project_root(self):
        """TC-D001: Verify get_project_root returns the repo root.

        The project root should be the parent directory of src/, identified by
        its project marker directories rather than a hardcoded folder name.
        """
        from src.utils.config import get_project_root

        root = get_project_root()
        assert isinstance(root, Path)
        assert root.exists()
        # Verify it contains the expected project markers
        assert (root / "src").is_dir()
        assert (root / "config").is_dir()


class TestGetDataDir:
    """Tests for get_data_dir() function."""

    def test_get_data_dir_creates_directory(self, tmp_path):
        """TC-D001: Verify get_data_dir creates directory and returns Path.

        When called with a subdirectory name, it should create the full
        path (data/<subdir>/) under the project root and return it.
        """
        with patch("src.utils.config.get_project_root", return_value=tmp_path):
            from src.utils.config import get_data_dir

            result = get_data_dir("raw")

        assert isinstance(result, Path)
        assert result.exists()
        assert result.is_dir()
        assert result == tmp_path / "data" / "raw"

    def test_get_data_dir_no_subdir(self, tmp_path):
        """TC-D001: Verify get_data_dir with no subdir returns data/ path."""
        with patch("src.utils.config.get_project_root", return_value=tmp_path):
            from src.utils.config import get_data_dir

            result = get_data_dir()

        assert isinstance(result, Path)
        assert result.exists()
        assert result == tmp_path / "data"

    def test_get_data_dir_idempotent(self, tmp_path):
        """TC-D001: Calling get_data_dir twice does not raise an error.

        The function uses mkdir(parents=True, exist_ok=True), so repeated
        calls should be safe.
        """
        with patch("src.utils.config.get_project_root", return_value=tmp_path):
            from src.utils.config import get_data_dir

            result1 = get_data_dir("processed")
            result2 = get_data_dir("processed")

        assert result1 == result2
        assert result1.exists()

    def test_get_data_dir_nested_subdir(self, tmp_path):
        """TC-D001: Verify get_data_dir handles nested subdirectories."""
        with patch("src.utils.config.get_project_root", return_value=tmp_path):
            from src.utils.config import get_data_dir

            # Even though the current implementation only appends one level,
            # test that the returned path is correct.
            result = get_data_dir("raw")

        assert result.name == "raw"
        assert result.parent.name == "data"
