import json

from macmedic import config


def test_defaults_load(tmp_path):
    settings = config.load_config(str(tmp_path / "missing.json"))
    assert settings["thresholds"]["cpu_warn_pct"] == 75.0
    assert settings["alerts"]["enabled"] is True


def test_deep_merge_overrides_nested(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"thresholds": {"cpu_warn_pct": 60.0}}))
    settings = config.load_config(str(path))
    assert settings["thresholds"]["cpu_warn_pct"] == 60.0
    assert settings["thresholds"]["cpu_crit_pct"] == 90.0


def test_invalid_json_falls_back_to_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json")
    settings = config.load_config(str(path))
    assert settings["thresholds"]["cpu_crit_pct"] == 90.0


def test_get_dotted_path():
    assert config.get("thresholds.cpu_crit_pct") == 90.0
    assert config.get("does.not.exist", "fallback") == "fallback"


def test_get_float_and_int():
    assert config.get_float("thresholds.cpu_crit_pct", 1.0) == 90.0
    assert config.get_int("top_processes", 1) == 10
