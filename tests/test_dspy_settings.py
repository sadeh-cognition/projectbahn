from __future__ import annotations

from projbahn.dspy_settings import DSPySettings


def test_dspy_settings_uses_sane_defaults() -> None:
    config = DSPySettings()

    assert config.temperature == 0.2
    assert config.max_tokens == 1200
    assert config.cache_enabled is True
    assert config.mlflow_enabled is False
    assert config.mlflow_tracking_uri == "http://127.0.0.1:5000"
    assert config.mlflow_experiment_name == "Projbahn DSPy"


def test_dspy_settings_reads_environment_values(monkeypatch) -> None:
    monkeypatch.setenv("PROJBAHN_DSPY_TEMPERATURE", "0.7")
    monkeypatch.setenv("PROJBAHN_DSPY_MAX_TOKENS", "2400")
    monkeypatch.setenv("PROJBAHN_DSPY_CACHE_ENABLED", "false")
    monkeypatch.setenv("PROJBAHN_DSPY_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("PROJBAHN_DSPY_MLFLOW_TRACKING_URI", "http://mlflow:5000")
    monkeypatch.setenv("PROJBAHN_DSPY_MLFLOW_EXPERIMENT_NAME", "Custom Experiment")

    config = DSPySettings()

    assert config.temperature == 0.7
    assert config.max_tokens == 2400
    assert config.cache_enabled is False
    assert config.mlflow_enabled is True
    assert config.mlflow_tracking_uri == "http://mlflow:5000"
    assert config.mlflow_experiment_name == "Custom Experiment"
