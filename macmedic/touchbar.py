"""Touch Bar widget for MacMedic.

On MacBook Pros that still have a physical Touch Bar (2016–2020, including the
2020 13-inch Intel), this drops a tiny Control Strip chip showing live CPU
percent. Tapping it expands a system-modal bar with CPU, RAM, package temp,
fan RPM, and the health score.

This is a menu-bar extra (``LSUIElement``), so the public per-window
``NSTouchBar`` API never appears. The widget uses the same Control Strip /
system-modal entry point that apps like iStat Menus and Pock use:

* ``+[NSTouchBarItem addSystemTrayItem:]``
* ``+[NSTouchBar presentSystemModalTouchBar:systemTrayItemIdentifier:]``
* ``DFRElementSetControlStripPresenceForIdentifier`` (DFRFoundation)

Those symbols are loaded at runtime and skipped if anything is missing, so a
function-key Mac, Apple Silicon without a Touch Bar, or a Linux test run is a
silent no-op. No extra process, no extra timer — the existing 2-second poll
just refreshes the button titles.

AppKit / DFR are imported lazily so this module is safe to import in CI.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import subprocess
from typing import Any, Callable

log = logging.getLogger("macmedic.touchbar")

# Reverse-DNS identifiers. The strip id is what the Control Strip chip uses
# and what presentSystemModalTouchBar:systemTrayItemIdentifier: matches on.
STRIP_IDENT = "com.macmedic.app.touchbar.strip"
BAR_IDENT = "com.macmedic.app.touchbar"
CPU_IDENT = "com.macmedic.app.touchbar.cpu"
RAM_IDENT = "com.macmedic.app.touchbar.ram"
TEMP_IDENT = "com.macmedic.app.touchbar.temp"
FAN_IDENT = "com.macmedic.app.touchbar.fan"
HEALTH_IDENT = "com.macmedic.app.touchbar.health"
FLEX_IDENT = "NSTouchBarItemIdentifierFlexibleSpace"

# Every shipping Mac with a physical Touch Bar. The 2020 13-inch Intel with
# function keys is MacBookPro16,3 and is intentionally absent. 14/16-inch
# Apple silicon machines went back to function keys and are also absent.
TOUCHBAR_MODELS: frozenset[str] = frozenset(
    {
        "MacBookPro13,2",  # 2016 13" Touch Bar
        "MacBookPro13,3",  # 2016 15"
        "MacBookPro14,2",  # 2017 13" Touch Bar
        "MacBookPro14,3",  # 2017 15"
        "MacBookPro15,1",  # 2018–2019 15"
        "MacBookPro15,2",  # 2018–2019 13" Touch Bar
        "MacBookPro15,3",  # 2019 15"
        "MacBookPro15,4",  # 2019 13" Touch Bar
        "MacBookPro16,1",  # 2019 16"
        "MacBookPro16,2",  # 2020 13" Intel Touch Bar
        "MacBookPro16,4",  # 2019 16" (AMD)
        "MacBookPro17,1",  # 2020 13" M1 Touch Bar
    }
)

DFR_BUNDLE = "/System/Library/PrivateFrameworks/DFRFoundation.framework"

_FUNCS: dict[str, Any] = {}
_CONTROLLER_CLS: Any = None
_HOST: Any = None


def is_touchbar_model(model: str | None) -> bool:
    """True when ``hw.model`` is a Mac that shipped with a Touch Bar."""
    if not model:
        return False
    return model.strip() in TOUCHBAR_MODELS


def hardware_model() -> str | None:
    """Return ``hw.model`` (for example ``MacBookPro16,1``) without a subprocess."""
    try:
        path = ctypes.util.find_library("c")
        if not path:
            return None
        libc = ctypes.CDLL(path, use_errno=True)
        libc.sysctlbyname.argtypes = [
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        libc.sysctlbyname.restype = ctypes.c_int
        name = b"hw.model"
        size = ctypes.c_size_t(0)
        libc.sysctlbyname(name, None, ctypes.byref(size), None, 0)
        if size.value == 0:
            size = ctypes.c_size_t(64)
        buf = ctypes.create_string_buffer(size.value)
        size = ctypes.c_size_t(len(buf))
        if libc.sysctlbyname(name, buf, ctypes.byref(size), None, 0) != 0:
            return None
        model = buf.value.decode("utf-8", errors="replace").strip()
        return model or None
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("hw.model sysctl failed: %s", exc)
        return None


def format_strip_title(cpu: float) -> str:
    """Compact Control Strip title — fits the tiny chip, matches the menu bar."""
    return f"{cpu:02.0f}%"


def format_chips(state: dict[str, Any]) -> dict[str, str]:
    """Expanded-bar button titles from a snapshot dict."""
    cpu = float(state.get("cpu") or 0.0)
    ram = float(state.get("ram") or 0.0)
    temp = state.get("temp")
    fan = state.get("fan")
    health = state.get("health")
    return {
        "cpu": f"CPU {cpu:.0f}%",
        "ram": f"RAM {ram:.0f}%",
        "temp": f"{temp:.0f}°" if isinstance(temp, (int, float)) else "Temp —",
        "fan": f"{fan:.0f}" if isinstance(fan, (int, float)) else "Fan —",
        "health": f"H {int(health)}" if isinstance(health, (int, float)) else "H —",
    }


def severity_level(
    cpu: float,
    ram: float,
    pressure: int,
    temp: float | None = None,
    *,
    cpu_warn: float = 75.0,
    cpu_crit: float = 90.0,
    ram_warn: float = 80.0,
    ram_crit: float = 92.0,
    temp_warn: float = 85.0,
    temp_crit: float = 95.0,
) -> int:
    """0 healthy, 1 warn, 2 critical — same thresholds as the menu-bar colour."""
    if cpu >= cpu_crit or ram >= ram_crit or pressure >= 3 or (temp is not None and temp >= temp_crit):
        return 2
    if cpu >= cpu_warn or ram >= ram_warn or pressure == 2 or (temp is not None and temp >= temp_warn):
        return 1
    return 0


def available() -> bool:
    """True when this Mac can host a Touch Bar widget.

    Requires the ``NSTouchBar`` class *and* either a known Touch Bar model or a
    running ``TouchBarServer`` (the process that only exists with hardware).
    """
    if _nstouchbar_class() is None:
        return False
    model = hardware_model()
    if is_touchbar_model(model):
        return True
    return _touchbar_server_running()


def _nstouchbar_class() -> Any:
    try:
        from AppKit import NSClassFromString

        return NSClassFromString("NSTouchBar")
    except Exception:
        return None


def _touchbar_server_running() -> bool:
    """``TouchBarServer`` is launched only on machines with a physical Touch Bar."""
    try:
        result = subprocess.run(["pgrep", "-qx", "TouchBarServer"], capture_output=True, timeout=1)
        return result.returncode == 0
    except Exception:  # pragma: no cover - defensive
        return False


def _bind_private_api() -> bool:
    """Load DFRFoundation Control Strip helpers. False if they are not there."""
    if "DFRElementSetControlStripPresenceForIdentifier" in _FUNCS:
        return True
    try:
        import objc

        if not os.path.isdir(DFR_BUNDLE):
            return False
        bundle = objc.loadBundle("DFRFoundation", {}, bundle_path=DFR_BUNDLE)
        if bundle is None:
            return False
        objc.loadBundleFunctions(
            bundle,
            _FUNCS,
            [
                ("DFRElementSetControlStripPresenceForIdentifier", b"v@B"),
                ("DFRSystemModalShowsCloseBoxWhenFrontMost", b"vB"),
            ],
        )
        return "DFRElementSetControlStripPresenceForIdentifier" in _FUNCS
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("DFRFoundation bind failed: %s", exc)
        return False


def _set_strip_presence(ident: str, present: bool) -> None:
    fn = _FUNCS.get("DFRElementSetControlStripPresenceForIdentifier")
    if fn is None:
        return
    try:
        fn(ident, present)
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("DFR strip presence failed: %s", exc)


def _set_close_box(show: bool) -> None:
    fn = _FUNCS.get("DFRSystemModalShowsCloseBoxWhenFrontMost")
    if fn is None:
        return
    try:
        fn(show)
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("DFR close-box failed: %s", exc)


def _controller_class() -> Any:
    """Build the PyObjC controller once, on first install, on macOS only."""
    global _CONTROLLER_CLS
    if _CONTROLLER_CLS is not None:
        return _CONTROLLER_CLS

    import objc
    from AppKit import (
        NSButton,
        NSColor,
        NSCustomTouchBarItem,
        NSFont,
        NSObject,
        NSTouchBar,
        NSTouchBarItem,
    )

    class TouchBarController(NSObject):
        def initWithCallbacks_(self, callbacks):
            self = objc.super(TouchBarController, self).init()
            if self is None:
                return None
            self._callbacks = callbacks or {}
            self._buttons: dict[str, Any] = {}
            self._bar: Any = None
            self._strip_item: Any = None
            self._strip_button: Any = None
            self._presented = False
            self._retain: list[Any] = []
            self._last_state: dict[str, Any] = {}
            return self

        @objc.python_method
        def install(self) -> bool:
            try:
                self._build_bar()
                self._install_strip()
            except Exception as exc:
                log.exception("touch bar install failed: %s", exc)
                return False
            return self._strip_item is not None

        @objc.python_method
        def _build_bar(self) -> None:
            bar = NSTouchBar.alloc().init()
            bar.setDelegate_(self)
            bar.setCustomizationIdentifier_(BAR_IDENT)
            bar.setDefaultItemIdentifiers_([CPU_IDENT, RAM_IDENT, TEMP_IDENT, FAN_IDENT, FLEX_IDENT, HEALTH_IDENT])
            bar.setPrincipalItemIdentifier_(CPU_IDENT)
            self._bar = bar
            self._retain.append(bar)

        @objc.python_method
        def _install_strip(self) -> None:
            btn = NSButton.buttonWithTitle_target_action_("--%", self, "stripClicked:")
            try:
                btn.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(15.0, 0.3))
            except Exception:
                pass
            item = NSCustomTouchBarItem.alloc().initWithIdentifier_(STRIP_IDENT)
            item.setView_(btn)
            item.setCustomizationLabel_("MacMedic")
            self._strip_button = btn
            self._strip_item = item
            self._retain.append(item)
            self._retain.append(btn)
            if hasattr(NSTouchBarItem, "addSystemTrayItem_"):
                NSTouchBarItem.addSystemTrayItem_(item)
            _set_close_box(True)
            _set_strip_presence(STRIP_IDENT, True)

        @objc.python_method
        def _present(self) -> None:
            if self._bar is None:
                return
            presented = False
            if hasattr(NSTouchBar, "presentSystemModalTouchBar_systemTrayItemIdentifier_"):
                NSTouchBar.presentSystemModalTouchBar_systemTrayItemIdentifier_(self._bar, STRIP_IDENT)
                presented = True
            elif hasattr(NSTouchBar, "presentSystemModalFunctionBar_systemTrayItemIdentifier_"):
                NSTouchBar.presentSystemModalFunctionBar_systemTrayItemIdentifier_(self._bar, STRIP_IDENT)
                presented = True
            self._presented = presented

        @objc.python_method
        def _minimize(self) -> None:
            if self._bar is None:
                return
            if hasattr(NSTouchBar, "minimizeSystemModalTouchBar_"):
                NSTouchBar.minimizeSystemModalTouchBar_(self._bar)
            elif hasattr(NSTouchBar, "minimizeSystemModalFunctionBar_"):
                NSTouchBar.minimizeSystemModalFunctionBar_(self._bar)
            self._presented = False

        @objc.python_method
        def update(self, state: dict[str, Any]) -> None:
            self._last_state = dict(state)
            chips = format_chips(state)
            cpu = float(state.get("cpu") or 0.0)
            ram = float(state.get("ram") or 0.0)
            pressure = int(state.get("pressure") or 1)
            temp = state.get("temp")
            temp_f = float(temp) if isinstance(temp, (int, float)) else None
            level = severity_level(
                cpu,
                ram,
                pressure,
                temp_f,
                cpu_warn=float(state.get("cpu_warn", 75.0)),
                cpu_crit=float(state.get("cpu_crit", 90.0)),
                ram_warn=float(state.get("ram_warn", 80.0)),
                ram_crit=float(state.get("ram_crit", 92.0)),
                temp_warn=float(state.get("temp_warn", 85.0)),
                temp_crit=float(state.get("temp_crit", 95.0)),
            )
            if self._strip_button is not None:
                self._strip_button.setTitle_(format_strip_title(cpu))
                try:
                    self._strip_button.setBezelColor_(self._severity_color(level))
                except Exception:
                    pass
            mapping = {
                "cpu": (CPU_IDENT, chips["cpu"], self._usage_color(cpu, state)),
                "ram": (RAM_IDENT, chips["ram"], self._usage_color(ram, state, kind="ram")),
                "temp": (TEMP_IDENT, chips["temp"], self._temp_color(temp_f, state)),
                "fan": (FAN_IDENT, chips["fan"], NSColor.controlAccentColor()),
                "health": (HEALTH_IDENT, chips["health"], self._health_color(state.get("health"))),
            }
            for ident, title, color in mapping.values():
                btn = self._buttons.get(ident)
                if btn is None:
                    continue
                btn.setTitle_(title)
                try:
                    btn.setBezelColor_(color)
                except Exception:
                    pass

        @objc.python_method
        def teardown(self) -> None:
            try:
                if self._bar is not None:
                    if hasattr(NSTouchBar, "dismissSystemModalTouchBar_"):
                        NSTouchBar.dismissSystemModalTouchBar_(self._bar)
                    elif hasattr(NSTouchBar, "dismissSystemModalFunctionBar_"):
                        NSTouchBar.dismissSystemModalFunctionBar_(self._bar)
                    self._bar.setDelegate_(None)
                _set_strip_presence(STRIP_IDENT, False)
                if self._strip_item is not None and hasattr(NSTouchBarItem, "removeSystemTrayItem_"):
                    NSTouchBarItem.removeSystemTrayItem_(self._strip_item)
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("touch bar teardown failed: %s", exc)
            self._presented = False
            self._bar = None
            self._strip_item = None
            self._strip_button = None
            self._buttons = {}

        def stripClicked_(self, sender) -> None:
            if self._presented:
                self._minimize()
            else:
                self._present()

        def cpuClicked_(self, sender) -> None:
            self._fire("on_sensors")

        def ramClicked_(self, sender) -> None:
            self._fire("on_sensors")

        def tempClicked_(self, sender) -> None:
            self._fire("on_sensors")

        def fanClicked_(self, sender) -> None:
            self._fire("on_sensors")

        def healthClicked_(self, sender) -> None:
            self._fire("on_health")

        @objc.python_method
        def _fire(self, name: str) -> None:
            fn = self._callbacks.get(name)
            if callable(fn):
                try:
                    fn()
                except Exception as exc:  # pragma: no cover - defensive
                    log.debug("touch bar callback %s failed: %s", name, exc)

        def touchBar_makeItemForIdentifier_(self, bar, ident):
            if ident in (None, FLEX_IDENT):
                return None
            actions = {
                CPU_IDENT: "cpuClicked:",
                RAM_IDENT: "ramClicked:",
                TEMP_IDENT: "tempClicked:",
                FAN_IDENT: "fanClicked:",
                HEALTH_IDENT: "healthClicked:",
            }
            action = actions.get(ident)
            if action is None:
                return None
            title = {
                CPU_IDENT: "CPU —",
                RAM_IDENT: "RAM —",
                TEMP_IDENT: "Temp —",
                FAN_IDENT: "Fan —",
                HEALTH_IDENT: "H —",
            }[ident]
            btn = NSButton.buttonWithTitle_target_action_(title, self, action)
            try:
                btn.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(15.0, 0.3))
            except Exception:
                pass
            item = NSCustomTouchBarItem.alloc().initWithIdentifier_(ident)
            item.setView_(btn)
            item.setCustomizationLabel_(title.split()[0])
            self._buttons[ident] = btn
            self._retain.append(item)
            self._retain.append(btn)
            if self._last_state:
                self.update(self._last_state)
            return item

        @objc.python_method
        def _severity_color(self, level: int):
            if level >= 2:
                return NSColor.systemRedColor()
            if level == 1:
                return NSColor.systemOrangeColor()
            return NSColor.systemGreenColor()

        @objc.python_method
        def _usage_color(self, value: float, state: dict[str, Any], kind: str = "cpu"):
            warn = float(state.get(f"{kind}_warn", 75.0 if kind == "cpu" else 80.0))
            crit = float(state.get(f"{kind}_crit", 90.0 if kind == "cpu" else 92.0))
            if value >= crit:
                return NSColor.systemRedColor()
            if value >= warn:
                return NSColor.systemOrangeColor()
            return NSColor.systemBlueColor() if kind == "cpu" else NSColor.systemIndigoColor()

        @objc.python_method
        def _temp_color(self, temp: float | None, state: dict[str, Any]):
            if temp is None:
                return NSColor.secondaryLabelColor()
            if temp >= float(state.get("temp_crit", 95.0)):
                return NSColor.systemRedColor()
            if temp >= float(state.get("temp_warn", 85.0)):
                return NSColor.systemOrangeColor()
            return NSColor.systemTealColor()

        @objc.python_method
        def _health_color(self, score: Any):
            if not isinstance(score, (int, float)):
                return NSColor.secondaryLabelColor()
            if score >= 75:
                return NSColor.systemGreenColor()
            if score >= 50:
                return NSColor.systemOrangeColor()
            return NSColor.systemRedColor()

    _CONTROLLER_CLS = TouchBarController
    return _CONTROLLER_CLS


class TouchBarHost:
    """Python-facing handle so ``app.py`` never talks to ObjC directly."""

    def __init__(self, controller: Any) -> None:
        self._controller = controller
        self._alive = True

    def update(self, state: dict[str, Any]) -> None:
        if self._alive:
            self._controller.update(state)

    def teardown(self) -> None:
        global _HOST
        if not self._alive:
            return
        self._alive = False
        try:
            self._controller.teardown()
        finally:
            if _HOST is self:
                _HOST = None


def install(
    on_sensors: Callable[..., Any] | None = None,
    on_health: Callable[..., Any] | None = None,
) -> TouchBarHost | None:
    """Attach the Control Strip chip. Returns None when the Mac cannot host it."""
    global _HOST
    if _HOST is not None:
        return _HOST
    if not available():
        log.info("Touch Bar widget skipped — this Mac has no Touch Bar")
        return None
    _bind_private_api()
    try:
        cls = _controller_class()
    except Exception as exc:  # pragma: no cover - AppKit missing
        log.debug("Touch Bar controller unavailable: %s", exc)
        return None
    controller = cls.alloc().initWithCallbacks_({"on_sensors": on_sensors, "on_health": on_health})
    if controller is None or not controller.install():
        log.info("Touch Bar widget skipped — Control Strip API unavailable")
        return None
    _HOST = TouchBarHost(controller)
    log.info("Touch Bar widget attached to the Control Strip")
    return _HOST


def teardown() -> None:
    global _HOST
    if _HOST is not None:
        try:
            _HOST.teardown()
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("touch bar host teardown failed: %s", exc)
        _HOST = None
