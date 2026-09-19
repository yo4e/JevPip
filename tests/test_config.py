from jevpip.config import list_profiles, load_profile


def test_builtin_profiles_include_moon_only():
    assert "moon_only" in list_profiles()
    assert load_profile("moon_only")["moon_phase"] is True
    assert load_profile("moon_only")["quote"] is False
