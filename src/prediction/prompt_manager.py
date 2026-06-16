"""Prompt management system with YAML file storage.

Provides CRUD operations for prompt templates stored in config/prompts/*.yaml.
Supports version history tracking and usage counting.

Per PRD v2.5 FR-PM001.
"""

import copy
import time
import uuid
from pathlib import Path
from typing import Any

import yaml

from src.utils.logger import get_logger

logger = get_logger("prediction.prompt_manager")

PROMPTS_DIR = Path("config/prompts")


class PromptManager:
    """Manages prompt templates stored as YAML files.

    Provides CRUD operations, version history, and usage tracking.
    """

    def __init__(self, prompts_dir: Path | str = PROMPTS_DIR) -> None:
        self._dir = Path(prompts_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict[str, Any]] | None = None

    def _load_all(self) -> dict[str, dict[str, Any]]:
        """Load all prompts from YAML files into memory."""
        if self._cache is not None:
            return self._cache
        prompts: dict[str, dict[str, Any]] = {}
        for yaml_file in sorted(self._dir.glob("*.yaml")):
            try:
                with open(yaml_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                for p in data.get("prompts", []):
                    pid = p.get("id")
                    if pid:
                        p["_source_file"] = yaml_file.name
                        prompts[pid] = p
            except Exception as exc:
                logger.warning("Failed to load %s: %s", yaml_file, exc)
        self._cache = prompts
        return prompts

    def _invalidate_cache(self) -> None:
        self._cache = None

    def _save_prompt(
        self, prompt: dict[str, Any], filename: str = "custom_prompts.yaml"
    ) -> None:
        """Save a single prompt to a YAML file."""
        filepath = self._dir / filename
        data: dict[str, Any] = {"prompts": []}
        if filepath.exists():
            with open(filepath, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {"prompts": []}

        # Replace existing or append
        existing = [p for p in data.get("prompts", []) if p.get("id") != prompt["id"]]
        clean_prompt = {k: v for k, v in prompt.items() if not k.startswith("_")}
        existing.append(clean_prompt)
        data["prompts"] = existing

        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(
                data, f, allow_unicode=True, default_flow_style=False, sort_keys=False
            )
        self._invalidate_cache()

    def _save_all_to_file(self, prompts: list[dict[str, Any]], filename: str) -> None:
        """Save a list of prompts to a specific YAML file."""
        filepath = self._dir / filename
        clean = [{k: v for k, v in p.items() if not k.startswith("_")} for p in prompts]
        data = {"prompts": clean}
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(
                data, f, allow_unicode=True, default_flow_style=False, sort_keys=False
            )
        self._invalidate_cache()

    def list_prompts(self) -> list[dict[str, Any]]:
        """List all prompt templates."""
        prompts = self._load_all()
        result = []
        for pid, p in prompts.items():
            result.append(
                {
                    "id": pid,
                    "name": p.get("name", ""),
                    "category": p.get("category", ""),
                    "description": p.get("description", ""),
                    "tags": p.get("tags", []),
                    "variables": p.get("variables", []),
                    "usage_count": p.get("usage_count", 0),
                    "updated_at": p.get("updated_at"),
                    "created_at": p.get("created_at"),
                }
            )
        return result

    def get_prompt(self, prompt_id: str) -> dict[str, Any] | None:
        """Get a single prompt template by ID, including full content and history."""
        prompts = self._load_all()
        p = prompts.get(prompt_id)
        if p is None:
            return None
        result = copy.deepcopy(p)
        result.pop("_source_file", None)
        return result

    def create_prompt(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new prompt template."""
        prompt_id = data.get("id") or str(uuid.uuid4())[:8]
        prompts = self._load_all()
        if prompt_id in prompts:
            raise ValueError(f"Prompt ID '{prompt_id}' already exists")

        now = time.strftime("%Y-%m-%d %H:%M:%S")
        prompt: dict[str, Any] = {
            "id": prompt_id,
            "name": data.get("name", "Untitled"),
            "category": data.get("category", "custom"),
            "description": data.get("description", ""),
            "system_template": data.get("system_template", ""),
            "user_template": data.get("user_template", ""),
            "variables": data.get("variables", []),
            "tags": data.get("tags", []),
            "usage_count": 0,
            "created_at": now,
            "updated_at": now,
            "version_history": [],
        }
        self._save_prompt(prompt, "custom_prompts.yaml")
        logger.info("Created prompt: %s", prompt_id)
        return {k: v for k, v in prompt.items() if not k.startswith("_")}

    def update_prompt(
        self, prompt_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update an existing prompt, recording previous version in history."""
        prompts = self._load_all()
        existing = prompts.get(prompt_id)
        if existing is None:
            return None

        # Record version history
        history = existing.get("version_history", [])
        history_entry = {
            "version": len(history) + 1,
            "timestamp": existing.get("updated_at", ""),
            "system_template": existing.get("system_template", ""),
            "user_template": existing.get("user_template", ""),
        }
        history.append(history_entry)

        # Update fields
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        for field in (
            "name",
            "category",
            "description",
            "system_template",
            "user_template",
            "variables",
            "tags",
        ):
            if field in data:
                existing[field] = data[field]
        existing["updated_at"] = now
        existing["version_history"] = history

        source_file = existing.get("_source_file", "custom_prompts.yaml")
        # Collect all prompts from same file and save
        all_in_file = [
            p for p in prompts.values() if p.get("_source_file") == source_file
        ]
        self._save_all_to_file(all_in_file, source_file)
        logger.info("Updated prompt: %s (version %d)", prompt_id, len(history) + 1)
        result = copy.deepcopy(existing)
        result.pop("_source_file", None)
        return result

    def delete_prompt(self, prompt_id: str) -> bool:
        """Delete a prompt template."""
        prompts = self._load_all()
        existing = prompts.get(prompt_id)
        if existing is None:
            return False

        source_file = existing.get("_source_file", "custom_prompts.yaml")
        remaining = [
            p
            for p in prompts.values()
            if p.get("_source_file") == source_file and p.get("id") != prompt_id
        ]
        self._save_all_to_file(remaining, source_file)
        logger.info("Deleted prompt: %s", prompt_id)
        return True

    def increment_usage(self, prompt_id: str) -> None:
        """Increment usage count for a prompt."""
        prompts = self._load_all()
        existing = prompts.get(prompt_id)
        if existing is None:
            return
        existing["usage_count"] = existing.get("usage_count", 0) + 1
        source_file = existing.get("_source_file", "custom_prompts.yaml")
        all_in_file = [
            p for p in prompts.values() if p.get("_source_file") == source_file
        ]
        self._save_all_to_file(all_in_file, source_file)

    def get_template(self, prompt_id: str) -> tuple[str, str] | None:
        """Get system and user templates for a prompt ID.

        Returns:
            Tuple of (system_template, user_template) or None if not found.
        """
        p = self.get_prompt(prompt_id)
        if p is None:
            return None
        return (p.get("system_template", ""), p.get("user_template", ""))
