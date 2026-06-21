from zcli.config import Settings


def test_recovery_settings_load_from_project_config(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    config_dir = workspace / ".zcli"
    config_dir.mkdir(parents=True)
    (config_dir / "config.env").write_text(
        "FALLBACK_MODEL_ID=backup-model\n"
        "ZCLI_MAX_TOKENS=1000\n"
        "ZCLI_ESCALATED_MAX_TOKENS=2000\n"
        "ZCLI_MAX_RETRIES=4\n"
        "ZCLI_MAX_RECOVERY_RETRIES=3\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for key in (
        "FALLBACK_MODEL_ID",
        "ZCLI_MAX_TOKENS",
        "ZCLI_ESCALATED_MAX_TOKENS",
        "ZCLI_MAX_RETRIES",
        "ZCLI_MAX_RECOVERY_RETRIES",
        "ZCLI_DATA_DIR",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = Settings.load(workspace)

    assert settings.fallback_model == "backup-model"
    assert settings.max_tokens == 1000
    assert settings.escalated_max_tokens == 2000
    assert settings.max_retries == 4
    assert settings.max_recovery_retries == 3
