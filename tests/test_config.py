from jevpip.config import Settings, list_profiles, load_profile, update_local_credentials


def test_builtin_profiles_include_moon_only():
    assert "moon_only" in list_profiles()
    assert load_profile("moon_only")["moon_phase"] is True
    assert load_profile("moon_only")["quote"] is False


def test_context_refresh_default_is_fifteen_minutes():
    settings = Settings()
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
