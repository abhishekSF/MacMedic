import struct

from macmedic.smc import _decode, _key_int


def test_sp78_temperature_decode():
    raw = struct.pack(">h", int(51.2 * 256))
    value = _decode("sp78", 2, raw)
    assert value is not None
    assert abs(value - 51.2) < 0.01


def test_sp78_signed_negative():
    raw = struct.pack(">h", int(-5.0 * 256))
    value = _decode("sp78", 2, raw)
    assert value is not None
    assert abs(value + 5.0) < 0.01


def test_fp79_unsigned_fixpoint():
    raw = struct.pack(">H", int(42.0 * 512))
    value = _decode("fp79", 2, raw)
    assert value is not None
    assert abs(value - 42.0) < 0.01


def test_fpe2_fan_value():
    raw = struct.pack(">H", 4 * 2100)
    value = _decode("fpe2", 2, raw)
    assert value is not None
    assert value == 2100.0


def test_flt_host_endian():
    raw = struct.pack("f", 1217.7)
    value = _decode("flt", 4, raw)
    assert value is not None
    assert abs(value - 1217.7) < 0.01


def test_ui8():
    assert _decode("ui8", 1, b"\x05") == 5.0


def test_empty_and_invalid_return_none():
    assert _decode("sp78", 2, b"") is None
    assert _decode("sp78", 1, b"\x01") == 1.0  # 1-byte sp78 = integer part only
    assert _decode("bogus", 4, b"\x00\x00\x00\x00") is None


def test_key_int_round_trip():
    assert _key_int("TC0P") == int.from_bytes(b"TC0P", "big")


def test_key_int_rejects_wrong_length():
    import pytest

    with pytest.raises(ValueError):
        _key_int("TOOLONG")
