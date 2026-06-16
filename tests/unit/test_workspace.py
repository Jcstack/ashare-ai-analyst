"""Tests for workspace directory utilities."""

from src.utils.config import get_project_root, get_workspace_dir


def test_get_workspace_dir_root(tmp_path, monkeypatch):
    """get_workspace_dir('') returns <root>/workspace/ and creates it."""
    monkeypatch.setattr("src.utils.config.get_project_root", lambda: tmp_path)
    result = get_workspace_dir()
    assert result == tmp_path / "workspace"
    assert result.is_dir()


def test_get_workspace_dir_subdir(tmp_path, monkeypatch):
    """get_workspace_dir('signals') returns nested subdir and creates it."""
    monkeypatch.setattr("src.utils.config.get_project_root", lambda: tmp_path)
    result = get_workspace_dir("signals")
    assert result == tmp_path / "workspace" / "signals"
    assert result.is_dir()


def test_get_workspace_dir_nested_subdir(tmp_path, monkeypatch):
    """get_workspace_dir('reports/deep') creates nested subdirectories."""
    monkeypatch.setattr("src.utils.config.get_project_root", lambda: tmp_path)
    result = get_workspace_dir("reports/deep")
    assert result == tmp_path / "workspace" / "reports" / "deep"
    assert result.is_dir()


def test_get_workspace_dir_idempotent(tmp_path, monkeypatch):
    """Calling get_workspace_dir twice on same subdir doesn't error."""
    monkeypatch.setattr("src.utils.config.get_project_root", lambda: tmp_path)
    first = get_workspace_dir("cache")
    second = get_workspace_dir("cache")
    assert first == second
    assert first.is_dir()


def test_get_workspace_dir_relative_to_project_root():
    """Real workspace dir is under the actual project root."""
    root = get_project_root()
    workspace = get_workspace_dir()
    assert workspace == root / "workspace"
