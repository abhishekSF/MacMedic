"""AppleSMC reader via IOKit.

On Intel Macs the System Management Controller exposes CPU/GPU temperatures
and fan RPM through a public IOKit user client that does **not** require root.
This module talks to ``AppleSMC`` through ctypes so the app can show real
thermal data on EOL Intel MacBooks without any helper daemon.

Every call is defensive: any failure returns ``None`` and the reader is
re-opened lazily on the next attempt. Verified against the 2019-2020 16-inch
MacBook Pro (sp78 temps, little-endian ``flt`` fan RPM).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import struct
import threading

log = logging.getLogger("macmedic.smc")

KERNEL_INDEX_SMC = 2
READ_BYTES = 5
READ_KEYINFO = 9

CPU_TEMP_KEYS: tuple[str, ...] = ("TC0P", "TC0E", "TC0D", "TC0C", "TC1C", "Tp0P", "Tp1P")
GPU_TEMP_KEYS: tuple[str, ...] = ("TG0P", "TG0D", "TG1P")

# Per-core die temperatures. Only the keys present on the machine are reported;
# core counts vary between 4- and 8-core Intel parts.
CORE_TEMP_KEYS: tuple[str, ...] = ("TC0C", "TC1C", "TC2C", "TC3C", "TC4C", "TC5C", "TC6C", "TC7C")

# Power draw in watts (big-endian float types or flt, decoded defensively).
# GPU power keys (PGTR/PG0R) are absent on many models — they are reported only
# when the SMC exposes them.
POWER_KEYS: dict[str, str] = {
    "system_w": "PSTR",
    "cpu_w": "PC0R",
    "gpu_w": "PGTR",
    "disk_w": "PDTR",
}

# Hard safety bounds for manual fan control when the SMC min/max keys are
# unreadable. Never exceed these regardless of user input.
FAN_MIN_RPM = 1000.0
FAN_MAX_RPM = 7000.0


class _Vers(ctypes.Structure):
    _fields_ = [
        ("major", ctypes.c_byte),
        ("minor", ctypes.c_byte),
        ("build", ctypes.c_byte),
        ("reserved", ctypes.c_byte),
        ("release", ctypes.c_uint16),
    ]


class _PLim(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_uint16),
        ("length", ctypes.c_uint16),
        ("cpuPLimit", ctypes.c_uint32),
        ("gpuPLimit", ctypes.c_uint32),
        ("memPLimit", ctypes.c_uint32),
    ]


class _KeyInfo(ctypes.Structure):
    _fields_ = [
        ("dataSize", ctypes.c_uint32),
        ("dataType", ctypes.c_uint32),
        ("dataAttributes", ctypes.c_byte),
    ]


class _SMCData(ctypes.Structure):
    _fields_ = [
        ("key", ctypes.c_uint32),
        ("vers", _Vers),
        ("pLim", _PLim),
        ("keyInfo", _KeyInfo),
        ("result", ctypes.c_byte),
        ("status", ctypes.c_byte),
        ("data8", ctypes.c_byte),
        ("data32", ctypes.c_uint32),
        ("bytes", ctypes.c_char * 32),
    ]


def _decode(dtype: str, size: int, raw: bytes) -> float | None:
    if not raw:
        return None
    if dtype == "sp78":
        if len(raw) >= 2:
            return struct.unpack(">h", raw[:2])[0] / 256.0
        return float(raw[0])
    if dtype.startswith("fpe") and len(raw) >= 2:
        return struct.unpack(">H", raw[:2])[0] / 4.0
    if len(dtype) >= 3 and dtype.startswith("fp") and len(raw) >= 2:
        try:
            intbits = int(dtype[2])
            return struct.unpack(">H", raw[:2])[0] / (1 << (16 - intbits))
        except ValueError:
            return None
    if len(dtype) >= 3 and dtype.startswith("sp") and len(raw) >= 2:
        try:
            intbits = int(dtype[2])
            return struct.unpack(">h", raw[:2])[0] / (1 << (16 - intbits))
        except ValueError:
            return None
    if dtype == "flt" and len(raw) >= 4:
        return struct.unpack("f", raw[:4])[0]
    if dtype == "ui8" and len(raw) >= 1:
        return float(raw[0])
    if dtype == "ui16" and len(raw) >= 2:
        return float(struct.unpack(">H", raw[:2])[0])
    if dtype == "ui32" and len(raw) >= 4:
        return float(struct.unpack(">I", raw[:4])[0])
    return None


def _key_int(name: str) -> int:
    if len(name) != 4:
        raise ValueError(f"bad SMC key: {name}")
    return struct.unpack(">I", name.encode())[0]


class SMCReader:
    """Thread-safe, lazily-opened AppleSMC client."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._conn: int | None = None
        self._io: ctypes.CDLL | None = None
        self._ok = False

    def _open(self) -> bool:
        if self._ok:
            return True
        try:
            import ctypes as c  # noqa: F401  (namespace helper)

            io = ctypes.CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")
            libc = ctypes.CDLL(ctypes.util.find_library("c"))
            io.IOServiceMatching.restype = ctypes.c_void_p
            io.IOServiceMatching.argtypes = [ctypes.c_char_p]
            io.IOServiceGetMatchingService.restype = ctypes.c_uint32
            io.IOServiceGetMatchingService.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
            io.IOServiceOpen.argtypes = [
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_uint32),
            ]
            io.IOServiceOpen.restype = ctypes.c_int
            io.IOConnectCallStructMethod.argtypes = [
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_void_p,
                ctypes.c_size_t,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_size_t),
            ]
            io.IOConnectCallStructMethod.restype = ctypes.c_int
            io.IOServiceClose.argtypes = [ctypes.c_uint32]
            io.IOServiceClose.restype = ctypes.c_int
            io.IOObjectRelease.argtypes = [ctypes.c_uint32]
            io.IOObjectRelease.restype = ctypes.c_int
            libc.mach_task_self.restype = ctypes.c_uint32

            service = io.IOServiceGetMatchingService(0, io.IOServiceMatching(b"AppleSMC"))
            if not service:
                return False
            conn = ctypes.c_uint32(0)
            status = io.IOServiceOpen(service, libc.mach_task_self(), 0, ctypes.byref(conn))
            io.IOObjectRelease(service)
            if status != 0 or not conn.value:
                return False
            self._conn = int(conn.value)
            self._io = io
            self._ok = True
            return True
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("SMC open failed: %s", exc)
            self._close()
            return False

    def _close(self) -> None:
        try:
            if self._conn is not None and self._io is not None:
                self._io.IOServiceClose(self._conn)
        except Exception:
            pass
        self._conn = None
        self._io = None
        self._ok = False

    def read_raw(self, name: str) -> tuple[str, int, bytes] | None:
        with self._lock:
            if not self._open():
                return None
            result = self._read_raw_once(name)
            if result is None:
                result = self._read_raw_once(name)
            return result

    def _read_raw_once(self, name: str) -> tuple[str, int, bytes] | None:
        try:
            key = _key_int(name)
            input_struct = _SMCData()
            input_struct.key = key
            input_struct.data8 = READ_KEYINFO
            output = self._call(input_struct)
            if output is None:
                return None
            dtype = output.keyInfo.dataType.to_bytes(4, "big").rstrip(b" ").decode()
            size = output.keyInfo.dataSize
            if size <= 0 or size > 8:
                return None
            input_struct2 = _SMCData()
            input_struct2.key = key
            input_struct2.data8 = READ_BYTES
            input_struct2.keyInfo.dataSize = size
            output2 = self._call(input_struct2)
            if output2 is None:
                return None
            return dtype, size, bytes(output2.bytes[:size])
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("SMC read %s failed: %s", name, exc)
            return None

    def _call(self, input_struct: _SMCData) -> _SMCData | None:
        if self._io is None or self._conn is None:
            return None
        output = _SMCData()
        size = ctypes.c_size_t(ctypes.sizeof(_SMCData))
        result = self._io.IOConnectCallStructMethod(
            self._conn,
            KERNEL_INDEX_SMC,
            ctypes.byref(input_struct),
            ctypes.sizeof(_SMCData),
            ctypes.byref(output),
            ctypes.byref(size),
        )
        if result != 0:
            return None
        return output

    def write_key(self, name: str, value: bytes) -> bool:
        """Write raw bytes to a whitelisted SMC key (fan mode / target RPM).

        The AppleSMC user client accepts a ``key`` plus ``data8`` (payload size)
        plus the payload in ``bytes`` using the same select index as reads.
        """
        with self._lock:
            if not self._open():
                return False
            try:
                input_struct = _SMCData()
                input_struct.key = _key_int(name)
                input_struct.data8 = len(value)
                payload = (value + b"\x00" * 32)[:32]
                for i, byte in enumerate(payload):
                    input_struct.bytes[i] = byte
                output = _SMCData()
                size = ctypes.c_size_t(ctypes.sizeof(_SMCData))
                if self._io is None or self._conn is None:
                    return False
                result = self._io.IOConnectCallStructMethod(
                    self._conn,
                    KERNEL_INDEX_SMC,
                    ctypes.byref(input_struct),
                    ctypes.sizeof(_SMCData),
                    ctypes.byref(output),
                    ctypes.byref(size),
                )
                return result == 0
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("SMC write %s failed: %s", name, exc)
                return False

    def fan_bounds(self, index: int = 0) -> tuple[float, float]:
        """Return (min, max) RPM the SMC allows for this fan."""
        minimum = self.read_key(f"F{index}Mn")
        maximum = self.read_key(f"F{index}Mx")
        lo = minimum if minimum is not None and 0.0 <= minimum <= 10000.0 else FAN_MIN_RPM
        hi = maximum if maximum is not None and lo <= maximum <= 20000.0 else FAN_MAX_RPM
        return lo, max(lo, hi)

    def set_fan_manual(self, rpm: float, index: int = 0) -> bool:
        """Put a fan in manual mode at a target RPM, clamped to SMC bounds."""
        lo, hi = self.fan_bounds(index)
        clamped = min(max(float(rpm), lo), hi)
        mode_ok = self.write_key(f"F{index}Md", b"\x01")
        target_ok = self.write_key(f"F{index}Tg", struct.pack("<f", clamped))
        return mode_ok and target_ok

    def set_fan_auto(self, index: int = 0) -> bool:
        """Return a fan to automatic SMC-controlled mode."""
        return self.write_key(f"F{index}Md", b"\x00")

    def read_key(self, name: str) -> float | None:
        raw = self.read_raw(name)
        if raw is None:
            return None
        dtype, size, data = raw
        value = _decode(dtype, size, data)
        if value is None:
            log.debug("unhandled SMC type %s for %s (size %d)", dtype, name, size)
        return value

    def cpu_temp(self) -> float | None:
        for key in CPU_TEMP_KEYS:
            value = self.read_key(key)
            if value is not None and 0.0 <= value <= 120.0:
                return value
        return None

    def gpu_temp(self) -> float | None:
        for key in GPU_TEMP_KEYS:
            value = self.read_key(key)
            if value is not None and 0.0 <= value <= 120.0:
                return value
        return None

    def fan_count(self) -> int | None:
        count = self.read_key("FNum")
        if count is None:
            return None
        return int(count) if 0 <= count <= 8 else None

    def fan_rpm(self, index: int = 0) -> float | None:
        if index > 8:
            return None
        value = self.read_key(f"F{index}Ac")
        if value is not None and 0.0 <= value <= 30000.0:
            return value
        return None

    def core_temps(self) -> dict[str, float]:
        """Return ``{key: temperature}`` for every core temperature key present."""
        cores: dict[str, float] = {}
        for key in CORE_TEMP_KEYS:
            value = self.read_key(key)
            if value is not None and 0.0 <= value <= 120.0:
                cores[key] = value
        return cores

    def power_readings(self) -> dict[str, float]:
        """Return ``{label: watts}`` for every power key the SMC exposes."""
        readings: dict[str, float] = {}
        for label, key in POWER_KEYS.items():
            value = self.read_key(key)
            if value is not None and 0.0 <= value <= 200.0:
                readings[label] = value
        return readings


_singleton: SMCReader | None = None
_singleton_lock = threading.Lock()


def get_smc() -> SMCReader | None:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = SMCReader()
    return _singleton


def cpu_temperature() -> float | None:
    reader = get_smc()
    if reader is None:
        return None
    return reader.cpu_temp()


def gpu_temperature() -> float | None:
    reader = get_smc()
    if reader is None:
        return None
    return reader.gpu_temp()


def fan_rpm(index: int = 0) -> float | None:
    reader = get_smc()
    if reader is None:
        return None
    return reader.fan_rpm(index)


def core_temps() -> dict[str, float]:
    reader = get_smc()
    if reader is None:
        return {}
    return reader.core_temps()


def power_readings() -> dict[str, float]:
    reader = get_smc()
    if reader is None:
        return {}
    return reader.power_readings()


def fan_bounds(index: int = 0) -> tuple[float, float]:
    reader = get_smc()
    if reader is None:
        return FAN_MIN_RPM, FAN_MAX_RPM
    return reader.fan_bounds(index)


def set_fan_manual(rpm: float, index: int = 0) -> bool:
    """Set a fan to a manual target RPM (clamped to safe bounds)."""
    reader = get_smc()
    if reader is None:
        return False
    return reader.set_fan_manual(rpm, index)


def restore_fan_auto(index: int = 0) -> bool:
    """Return a fan to automatic SMC-controlled mode."""
    reader = get_smc()
    if reader is None:
        return False
    return reader.set_fan_auto(index)
