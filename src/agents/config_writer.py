"""Read and write config.yaml, preserving ${ENV_VAR} references."""
import re
from pathlib import Path

import yaml


def is_env_var(value: str) -> bool:
    """Check if a string value is an env var reference like ${FOO}."""
    if not isinstance(value, str):
        return False
    return bool(re.fullmatch(r"\$\{\w+\}", value.strip()))


def read_raw_config(path: Path) -> dict:
    """Read config.yaml without resolving env vars."""
    return yaml.safe_load(path.read_text()) or {}


def _deep_merge(base: dict, updates: dict) -> dict:
    """Merge updates into base, only overwriting leaf values."""
    merged = dict(base)
    for key, value in updates.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _strip_env_vars(current: dict, updates: dict) -> dict:
    """Remove update keys where the current value is an env var reference."""
    clean: dict = {}
    for key, value in updates.items():
        cur = current.get(key)
        if isinstance(value, dict) and isinstance(cur, dict):
            nested = _strip_env_vars(cur, value)
            if nested:
                clean[key] = nested
        elif not is_env_var(str(cur or "")):
            clean[key] = value
    return clean


def write_config_values(path: Path, updates: dict) -> None:
    """Update specific values in config.yaml, preserving structure and env vars."""
    current = read_raw_config(path)
    safe_updates = _strip_env_vars(current, updates)
    merged = _deep_merge(current, safe_updates)
    path.write_text(yaml.dump(merged, default_flow_style=False, sort_keys=False))
