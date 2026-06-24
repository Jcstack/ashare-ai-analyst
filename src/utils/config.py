"""Configuration loader for the A-share analysis system.

Loads YAML configuration files from the config/ directory.
All runtime parameters are config-driven per PRD NFR-003.
"""

import re
from pathlib import Path
from typing import Any

import yaml

# Config names are simple lowercase identifiers (e.g. "llm", "recommendation").
# Restricting to this pattern prevents path traversal via crafted names.
_CONFIG_NAME_PATTERN = re.compile(r"[a-z0-9_]+")


def get_project_root() -> Path:
    """Get the project root directory.

    Returns:
        Path to the project root (parent of src/).
    """
    return Path(__file__).resolve().parent.parent.parent


def get_data_dir(subdir: str = "") -> Path:
    """Get the data directory path.

    Args:
        subdir: Optional subdirectory within data/ (e.g., "raw", "processed").

    Returns:
        Path to the data directory or subdirectory.
    """
    data_dir = get_project_root() / "data"
    if subdir:
        data_dir = data_dir / subdir
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_workspace_dir(subdir: str = "") -> Path:
    """Get the workspace directory path for research runtime artifacts.

    Args:
        subdir: Optional subdirectory within workspace/ (e.g., "signals",
            "reports/deep", "sentinel", "cache", "logs").

    Returns:
        Path to the workspace directory or subdirectory.
    """
    workspace_dir = get_project_root() / "workspace"
    if subdir:
        workspace_dir = workspace_dir / subdir
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return workspace_dir


def load_config(config_name: str) -> dict[str, Any]:
    """Load a YAML configuration file.

    Args:
        config_name: Name of the config file without extension
            (e.g., "stocks" loads config/stocks.yaml).

    Returns:
        Parsed configuration as a dictionary.

    Raises:
        FileNotFoundError: If the config file does not exist.
        yaml.YAMLError: If the YAML is malformed.
        ValueError: If config_name is not a simple lowercase identifier.
    """
    if not _CONFIG_NAME_PATTERN.fullmatch(config_name):
        raise ValueError(f"Invalid config name: {config_name!r}")
    config_dir = (get_project_root() / "config").resolve()
    config_path = (config_dir / f"{config_name}.yaml").resolve()
    if not config_path.is_relative_to(config_dir):
        raise ValueError(f"Invalid config name: {config_name!r}")
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    if config is None:
        return {}
    return config


def save_config(config_name: str, data: dict[str, Any]) -> None:
    """Write a configuration dict back to a YAML file.

    Creates a backup (.bak) before overwriting.

    Args:
        config_name: Name of the config file without extension
            (e.g., "stocks" writes to config/stocks.yaml).
        data: Configuration data to write.

    Raises:
        OSError: If file writing fails.
        ValueError: If config_name is not a simple lowercase identifier.
    """
    if not _CONFIG_NAME_PATTERN.fullmatch(config_name):
        raise ValueError(f"Invalid config name: {config_name!r}")
    config_dir = (get_project_root() / "config").resolve()
    config_path = (config_dir / f"{config_name}.yaml").resolve()
    if not config_path.is_relative_to(config_dir):
        raise ValueError(f"Invalid config name: {config_name!r}")
    # Create backup if file exists
    if config_path.exists():
        backup_path = config_path.with_suffix(".yaml.bak")
        backup_path.write_bytes(config_path.read_bytes())
    # Write new config
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            data, f, allow_unicode=True, default_flow_style=False, sort_keys=False
        )
