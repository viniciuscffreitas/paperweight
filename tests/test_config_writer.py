"""Tests for config_writer — read/write config.yaml preserving env var references."""
from pathlib import Path

from agents.config_writer import is_env_var, read_raw_config, write_config_values


def test_is_env_var_true():
    assert is_env_var("${LINEAR_API_KEY}") is True


def test_is_env_var_false():
    assert is_env_var("sonnet") is False
    assert is_env_var("") is False
    assert is_env_var("100.0") is False


def test_read_raw_config(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("budget:\n  daily_limit_usd: 50.00\nexecution:\n  default_model: sonnet\n")
    raw = read_raw_config(cfg)
    assert raw["budget"]["daily_limit_usd"] == 50.0
    assert raw["execution"]["default_model"] == "sonnet"


def test_write_config_values_updates_plain(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("budget:\n  daily_limit_usd: 50.00\n  pause_on_limit: true\n")
    write_config_values(cfg, {"budget": {"daily_limit_usd": 100.0}})
    raw = read_raw_config(cfg)
    assert raw["budget"]["daily_limit_usd"] == 100.0
    assert raw["budget"]["pause_on_limit"] is True  # unchanged


def test_write_config_values_preserves_env_vars(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("integrations:\n  linear_api_key: ${LINEAR_API_KEY}\n  github_token: my-token\n")
    write_config_values(cfg, {"integrations": {"github_token": "new-token"}})
    text = cfg.read_text()
    assert "${LINEAR_API_KEY}" in text  # env var preserved
    raw = read_raw_config(cfg)
    assert raw["integrations"]["github_token"] == "new-token"


def test_write_config_values_blocks_env_var_overwrite(tmp_path: Path):
    """Attempting to overwrite an env var field should be silently ignored."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("integrations:\n  linear_api_key: ${LINEAR_API_KEY}\n")
    write_config_values(cfg, {"integrations": {"linear_api_key": "hacked-value"}})
    raw = read_raw_config(cfg)
    assert raw["integrations"]["linear_api_key"] == "${LINEAR_API_KEY}"


def test_write_config_values_force_overwrites_env_vars(tmp_path: Path):
    """With force=True, env var fields CAN be overwritten."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("integrations:\n  linear_api_key: ${LINEAR_API_KEY}\n")
    write_config_values(
        cfg, {"integrations": {"linear_api_key": "sk-lin-real-key"}}, force=True
    )
    raw = read_raw_config(cfg)
    assert raw["integrations"]["linear_api_key"] == "sk-lin-real-key"


def test_write_config_values_force_empty_clears(tmp_path: Path):
    """With force=True, empty string replaces env var reference."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("integrations:\n  linear_api_key: ${LINEAR_API_KEY}\n")
    write_config_values(
        cfg, {"integrations": {"linear_api_key": ""}}, force=True
    )
    raw = read_raw_config(cfg)
    assert raw["integrations"]["linear_api_key"] == ""
