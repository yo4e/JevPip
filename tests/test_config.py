import os
from pathlib import Path

import pytest

import jevpip.config as config
from jevpip.config import Settings, list_profiles, load_profile, update_local_credentials


@pytest.fixture(autouse=True)
def isolate_settings_environment(monkeypatch):
    for field in Settings.model_fields:
        monkeypatch.delenv(field, raising=False)
        monkeypatch.delenv(field.upper(), raising=False)


def test_builtin_profiles_include_moon_only():
    assert "moon_only" in list_profiles()
    assert load_profile("moon_only")["moon_phase"] is True
    assert load_profile("moon_only")["quote"] is False


def test_context_refresh_default_is_fifteen_minutes():
    settings = Settings(_env_file=None)
    assert settings.context_refresh_seconds == 900.0



def test_update_local_credentials_preserves_unrelated_env_and_can_clear(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# local settings\nOTHER_SETTING=keep\nTYPESAFE_API_KEY=old\n",
        encoding="utf-8",
    )
    settings = Settings(_env_file=None)

    update_local_credentials(
        settings,
        typesafe_api_key="jev-secret",
        gmo_fx_api_key="gmo-key",
        gmo_fx_api_secret="gmo-secret",
        env_path=env_path,
    )

    saved = env_path.read_text(encoding="utf-8")
    assert "OTHER_SETTING=keep" in saved
    assert 'TYPESAFE_API_KEY="jev-secret"' in saved
    assert 'GMO_FX_API_KEY="gmo-key"' in saved
    assert 'GMO_FX_API_SECRET="gmo-secret"' in saved
    assert settings.typesafe_api_key == "jev-secret"
    assert settings.gmo_private_read_configured is True

    update_local_credentials(
        settings,
        clear_typesafe_api_key=True,
        clear_gmo_private_credentials=True,
        env_path=env_path,
    )
    saved = env_path.read_text(encoding="utf-8")
    assert "TYPESAFE_API_KEY" not in saved
    assert "GMO_FX_API_KEY" not in saved
    assert "GMO_FX_API_SECRET" not in saved
    assert "OTHER_SETTING=keep" in saved
    assert settings.typesafe_api_key is None
    assert settings.gmo_private_read_configured is False


@pytest.fixture
def stored_credentials(tmp_path):
    settings = Settings(
        _env_file=None,
        typesafe_api_key="fixture-old-typesafe",
        gmo_fx_api_key="fixture-old-gmo",
        gmo_fx_api_secret="fixture-old-secret",
    )
    env_path = tmp_path / ".env"
    env_path.write_text(
        '# fixture only\nOTHER_SETTING=keep\n'
        'TYPESAFE_API_KEY="fixture-old-typesafe"\n'
        'GMO_FX_API_KEY="fixture-old-gmo"\n'
        'GMO_FX_API_SECRET="fixture-old-secret"\n',
        encoding="utf-8",
    )
    return settings, env_path


@pytest.mark.parametrize("changes", [
    {"typesafe_api_key": "fixture-new-typesafe"},
    {"gmo_fx_api_key": "fixture-new-gmo", "gmo_fx_api_secret": "fixture-new-secret"},
    {"clear_typesafe_api_key": True},
    {"clear_gmo_private_credentials": True},
    {"clear_typesafe_api_key": True, "gmo_fx_api_key": "fixture-new-gmo"},
])
def test_failed_save_keeps_all_runtime_credentials(stored_credentials, monkeypatch, changes):
    settings, env_path = stored_credentials
    before = settings.model_dump()
    original = env_path.read_bytes()

    def fail_save(path, updates):
        raise PermissionError("fixture save failure")

    monkeypatch.setattr(config, "_write_env_values", fail_save)
    with pytest.raises(PermissionError, match="fixture save failure"):
        update_local_credentials(settings, env_path=env_path, **changes)

    assert settings.model_dump() == before
    assert env_path.read_bytes() == original


@pytest.mark.parametrize("changes", [
    {"typesafe_api_key": "fixture-new", "gmo_fx_api_key": " "},
    {"typesafe_api_key": "fixture-new", "gmo_fx_api_secret": "bad\nvalue"},
    {"gmo_fx_api_key": "fixture-new", "gmo_fx_api_secret": "bad\rvalue"},
    {"clear_typesafe_api_key": True, "gmo_fx_api_secret": " "},
])
def test_invalid_later_value_does_not_partially_update_settings(stored_credentials, changes):
    settings, env_path = stored_credentials
    before = settings.model_dump()
    original = env_path.read_bytes()

    with pytest.raises(ValueError):
        update_local_credentials(settings, env_path=env_path, **changes)

    assert settings.model_dump() == before
    assert env_path.read_bytes() == original
    assert not env_path.with_name(".env.tmp").exists()


@pytest.mark.parametrize("stage", ["write", "replace", "chmod"])
def test_file_failure_keeps_disk_and_runtime_settings(stored_credentials, monkeypatch, stage):
    if stage == "chmod" and os.name != "posix":
        pytest.skip("POSIX permission setting only")
    settings, env_path = stored_credentials
    before = settings.model_dump()
    original = env_path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError(f"fixture {stage} failure")

    if stage == "write":
        monkeypatch.setattr(Path, "write_text", fail)
    elif stage == "replace":
        monkeypatch.setattr(config.os, "replace", fail)
    else:
        monkeypatch.setattr(Path, "chmod", fail)

    with pytest.raises(OSError, match=f"fixture {stage} failure"):
        update_local_credentials(settings, typesafe_api_key="fixture-new", env_path=env_path)

    assert env_path.read_bytes() == original
    assert settings.model_dump() == before
    assert not env_path.with_name(".env.tmp").exists()


def test_success_publishes_cleaned_values_only_after_save(stored_credentials, monkeypatch):
    settings, env_path = stored_credentials
    before = settings.model_dump()
    write_env = config._write_env_values

    def check_before_save(path, updates):
        assert settings.model_dump() == before
        write_env(path, updates)

    monkeypatch.setattr(config, "_write_env_values", check_before_save)
    update_local_credentials(settings, typesafe_api_key="  fixture-new  ", env_path=env_path)

    assert settings.typesafe_api_key == "fixture-new"
    assert settings.gmo_fx_api_key == before["gmo_fx_api_key"]
    assert settings.gmo_fx_api_secret == before["gmo_fx_api_secret"]
    assert 'TYPESAFE_API_KEY="fixture-new"' in env_path.read_text(encoding="utf-8")
    assert "OTHER_SETTING=keep" in env_path.read_text(encoding="utf-8")
    assert not env_path.with_name(".env.tmp").exists()
    if os.name == "posix":
        assert env_path.stat().st_mode & 0o777 == 0o600


def test_no_changes_does_not_write(stored_credentials, monkeypatch):
    settings, env_path = stored_credentials
    before = settings.model_dump()

    def unexpected_write(*args, **kwargs):
        pytest.fail("No update should not write the file")

    monkeypatch.setattr(config, "_write_env_values", unexpected_write)
    update_local_credentials(settings, env_path=env_path)
    assert settings.model_dump() == before
