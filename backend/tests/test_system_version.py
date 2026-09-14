from app.services.system_version import get_system_version


def test_returns_env_override_when_set(monkeypatch, isolated_settings):
    monkeypatch.setenv("SYSTEM_VERSION", "v1.2.3-custom")
    from app.config.settings import get_settings

    get_settings.cache_clear()
    get_system_version.cache_clear()
    try:
        assert get_system_version() == "v1.2.3-custom"
    finally:
        get_settings.cache_clear()
        get_system_version.cache_clear()


def test_falls_back_to_git_commit_when_no_env_override(isolated_settings):
    get_system_version.cache_clear()
    try:
        version = get_system_version()
        # This repo IS a git checkout (Fase 9) -- expect a short hash,
        # optionally with a "-dirty" suffix, never the bare "unknown" fallback.
        assert version != "unknown"
        assert len(version.replace("-dirty", "")) >= 7
    finally:
        get_system_version.cache_clear()
