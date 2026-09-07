from macmedic.touchbar import (
    TOUCHBAR_MODELS,
    available,
    format_chips,
    format_strip_title,
    hardware_model,
    is_touchbar_model,
    severity_level,
)


def test_known_intel_touchbar_models():
    assert is_touchbar_model("MacBookPro16,1")  # 2019 16"
    assert is_touchbar_model("MacBookPro16,2")  # 2020 13" Intel Touch Bar
    assert is_touchbar_model("MacBookPro15,2")  # 2018–2019 13" Touch Bar
    assert is_touchbar_model("MacBookPro17,1")  # 2020 13" M1 Touch Bar
    assert "MacBookPro16,2" in TOUCHBAR_MODELS


def test_function_key_and_silicon_models_are_skipped():
    assert not is_touchbar_model("MacBookPro16,3")  # 2020 13" Intel, physical F-keys
    assert not is_touchbar_model("MacBookPro13,1")  # 2016 13" no Touch Bar
    assert not is_touchbar_model("MacBookPro18,1")  # 2021 16" M1 Pro
    assert not is_touchbar_model("MacBookAir10,1")
    assert not is_touchbar_model("")
    assert not is_touchbar_model(None)


def test_format_strip_title_matches_menu_bar_padding():
    assert format_strip_title(12.4) == "12%"
    assert format_strip_title(9.0) == "09%"
    assert format_strip_title(100.0) == "100%"


def test_format_chips_missing_sensors():
    chips = format_chips({"cpu": 10.4, "ram": 40.9, "temp": None, "fan": None, "health": None})
    assert chips["cpu"] == "CPU 10%"
    assert chips["ram"] == "RAM 41%"
    assert chips["temp"] == "Temp —"
    assert chips["fan"] == "Fan —"
    assert chips["health"] == "H —"


def test_format_chips_with_sensors():
    chips = format_chips({"cpu": 22, "ram": 57, "temp": 68.4, "fan": 2400.0, "health": 82})
    assert chips["temp"] == "68°"
    assert chips["fan"] == "2400"
    assert chips["health"] == "H 82"


def test_severity_level_matches_menu_bar_thresholds():
    assert severity_level(10, 10, 1, 50) == 0
    assert severity_level(80, 10, 1, 50) == 1
    assert severity_level(10, 85, 1, 50) == 1
    assert severity_level(10, 10, 2, 50) == 1
    assert severity_level(95, 10, 1, 50) == 2
    assert severity_level(10, 10, 3, 50) == 2
    assert severity_level(10, 10, 1, 96) == 2
    assert severity_level(10, 10, 1, 86) == 1


def test_available_returns_bool_and_is_false_without_hardware():
    """Off macOS this is always False. On a function-key Mac it is also False.

    A physical Touch Bar Mac will return True — that is the intended install
    path, so we only assert the type there.
    """
    result = available()
    assert isinstance(result, bool)
    from macmedic.touchbar import _nstouchbar_class

    if _nstouchbar_class() is None:
        assert result is False


def test_hardware_model_does_not_raise():
    # sysctl is a no-op off macOS; just prove it degrades.
    model = hardware_model()
    assert model is None or isinstance(model, str)
