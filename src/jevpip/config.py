from __future__ import annotations

from pathlib import Path
from typing import Any
import tomllib

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Private GMO credentials intentionally do not exist yet."""

    typesafe_api_key: str | None = None
    live_trading: bool = False
    data_dir: Path = Path("data")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def model_post_init(self, __context: Any) -> None:
        if self.live_trading:
            raise ValueError("LIVE_TRADING=true is not supported: JevPip has no live-order path.")


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
