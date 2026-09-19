from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any
import tomllib

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Live order paths remain intentionally unavailable."""

    typesafe_api_key: str | None = None
    gmo_fx_api_key: str | None = None
    gmo_fx_api_secret: str | None = None
    live_trading: bool = False
    data_dir: Path = Path("data")
    context_refresh_seconds: float = 900.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def model_post_init(self, __context: Any) -> None:
        if self.live_trading:
            raise ValueError("LIVE_TRADING=true is not supported: JevPip has no live-order path.")

    @property
    def gmo_private_read_configured(self) -> bool:
        return bool(self.gmo_fx_api_key and self.gmo_fx_api_secret)


def _clean_secret(value: str, *, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{label} cannot be empty")
    if "\n" in cleaned or "\r" in cleaned:
        raise ValueError(f"{label} cannot contain newlines")
    return cleaned


def _write_env_values(path: Path, updates: dict[str, str | None]) -> None:
    """Update selected .env values without exposing or rewriting unrelated settings."""

    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    matcher = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")
    output: list[str] = []
    seen: set[str] = set()

    for line in existing.splitlines():
        match = matcher.match(line)
        key = match.group(1) if match else None
        if key not in updates:
            output.append(line)
            continue
        if key in seen:
            continue
        seen.add(key)
        value = updates[key]
        if value is not None:
            output.append(f"{key}={json.dumps(value, ensure_ascii=False)}")

    for key, value in updates.items():
        if key in seen or value is None:
            continue
        output.append(f"{key}={json.dumps(value, ensure_ascii=False)}")

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        tmp_path.write_text(
            "\n".join(output) + ("\n" if output else ""),
            encoding="utf-8",
        )
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    if os.name == "posix":
        path.chmod(0o600)


def update_local_credentials(
    settings: Settings,
    *,
    typesafe_api_key: str | None = None,
    gmo_fx_api_key: str | None = None,
    gmo_fx_api_secret: str | None = None,
    clear_typesafe_api_key: bool = False,
    clear_gmo_private_credentials: bool = False,
    env_path: Path | None = None,
) -> None:
    """Persist local credentials to .env and update the live Settings object.

    Missing values mean "leave unchanged". Explicit clear flags remove stored values.
    Secret values are never returned by this helper.
    """

    updates: dict[str, str | None] = {}

    if clear_typesafe_api_key:
        updates["TYPESAFE_API_KEY"] = None
        settings.typesafe_api_key = None
    elif typesafe_api_key is not None:
        cleaned = _clean_secret(typesafe_api_key, label="TYPESAFE_API_KEY")
        updates["TYPESAFE_API_KEY"] = cleaned
        settings.typesafe_api_key = cleaned

    if clear_gmo_private_credentials:
        updates["GMO_FX_API_KEY"] = None
        updates["GMO_FX_API_SECRET"] = None
        settings.gmo_fx_api_key = None
        settings.gmo_fx_api_secret = None
    else:
        if gmo_fx_api_key is not None:
            cleaned = _clean_secret(gmo_fx_api_key, label="GMO_FX_API_KEY")
            updates["GMO_FX_API_KEY"] = cleaned
            settings.gmo_fx_api_key = cleaned
        if gmo_fx_api_secret is not None:
            cleaned = _clean_secret(gmo_fx_api_secret, label="GMO_FX_API_SECRET")
            updates["GMO_FX_API_SECRET"] = cleaned
            settings.gmo_fx_api_secret = cleaned

    if updates:
        _write_env_values(env_path or Path(".env"), updates)


def load_profile(name: str, config_path: Path | None = None) -> dict[str, Any]:
    if config_path is None:
        config_path = Path(__file__).with_name("profiles.toml")
    with config_path.open("rb") as fh:
        raw = tomllib.load(fh)
    profiles = raw.get("profile", {})
    if name not in profiles:
        available = ", ".join(sorted(profiles))
        raise ValueError(f"Unknown profile {name!r}. Available: {available}")
    return dict(profiles[name])


def list_profiles(config_path: Path | None = None) -> dict[str, dict[str, Any]]:
    if config_path is None:
        config_path = Path(__file__).with_name("profiles.toml")
    with config_path.open("rb") as fh:
        return dict(tomllib.load(fh).get("profile", {}))


def load_signal_policy(name: str, config_path: Path | None = None) -> tuple[dict[str, Any], str]:
    if config_path is None:
        config_path = Path(__file__).with_name("signals.toml")
    with config_path.open("rb") as fh:
        raw = tomllib.load(fh)
    policies = raw.get("signal", {})
    if name not in policies:
        available = ", ".join(sorted(policies))
        raise ValueError(f"Unknown signal policy {name!r}. Available: {available}")
    policy = dict(policies[name])
    description = str(policy.pop("description_ja", ""))
    return policy, description


def list_signal_policies(config_path: Path | None = None) -> dict[str, dict[str, Any]]:
    if config_path is None:
        config_path = Path(__file__).with_name("signals.toml")
    with config_path.open("rb") as fh:
        return dict(tomllib.load(fh).get("signal", {}))
