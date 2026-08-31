"""Custom Vorssaint-style popover panel for MacMedic.

rumps only renders an NSMenu dropdown, which cannot reproduce Vorssaint's
dark card UI (temperature tiles, colored usage bars with sparklines, a status
pill, and footer buttons). This module builds a real ``NSPopover`` backed by an
``NSVisualEffectView`` so the left-click UI matches that design. PyObjC is used
directly here; fonts, bars, and pills are drawn natively and adapt to the
system appearance.

Left-click on the status item toggles this panel; right-click still opens the
classic tool menu (see ``app.py``).
"""

from __future__ import annotations

import os
from typing import Any

import objc
from AppKit import (
    NSBezierPath,
    NSButton,
    NSColor,
    NSFont,
    NSPopover,
    NSPopoverBehaviorApplicationDefined,
    NSPopoverBehaviorTransient,
    NSScrollView,
    NSSlider,
    NSStackView,
    NSTextField,
    NSView,
    NSViewController,
    NSVisualEffectMaterialPopover,
    NSVisualEffectStateActive,
    NSVisualEffectView,
    NSZeroRect,
)
from Foundation import NSMakePoint, NSMakeRect, NSObject

WIDTH = 320
HEIGHT = 498

NS_RECT_EDGE_MIN_Y = 1  # NSRectEdgeMinY


def _label(text: str, size: int, color: Any, bold: bool = False) -> NSTextField:
    tf = NSTextField.alloc().initWithFrame_(NSZeroRect)
    tf.setBezeled_(False)
    tf.setDrawsBackground_(False)
    tf.setEditable_(False)
    tf.setSelectable_(False)
    tf.setStringValue_(text)
    font = NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size)
    tf.setFont_(font)
    tf.setTextColor_(color)
    tf.setLineBreakMode_(4)  # NSLineBreakByTruncatingTail
    return tf


class _Bar(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(_Bar, self).initWithFrame_(frame)
        if self is None:
            return None
        self._progress = 0.0
        self._color = NSColor.systemBlueColor()
        self.setWantsLayer_(True)
        return self

    def isOpaque(self):
        return False

    def applyProgress_(self, value):
        self._progress = max(0.0, min(1.0, float(value)))
        self.setNeedsDisplay_(True)

    def applyColor_(self, color):
        self._color = color
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        bg = self._color.colorWithAlphaComponent_(0.18)
        NSColor.clearColor().setFill()
        NSBezierPath.fillRect_(rect)
        radius = rect.size.height / 2.0
        if rect.size.width <= 0 or rect.size.height <= 0:
            return
        bg_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, radius, radius)
        bg.setFill()
        bg_path.fill()
        fill_w = max(0.0, min(rect.size.width, rect.size.width * self._progress))
        if fill_w > 0:
            fill_rect = NSMakeRect(rect.origin.x, rect.origin.y, fill_w, rect.size.height)
            fill_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(fill_rect, radius, radius)
            self._color.setFill()
            fill_path.fill()


class _Pill(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(_Pill, self).initWithFrame_(frame)
        if self is None:
            return None
        self._text = ""
        self._color = NSColor.systemGreenColor()
        self._tf = _label("", 12, NSColor.whiteColor(), bold=True)
        self.addSubview_(self._tf)
        self.setWantsLayer_(True)
        return self

    def isOpaque(self):
        return False

    def applyText_(self, text):
        self._text = text
        self._tf.setStringValue_(text)
        self.setNeedsDisplay_(True)

    def applyColor_(self, color):
        self._color = color
        self.setNeedsDisplay_(True)

    def layout(self):
        self._tf.setFrame_(NSMakeRect(0, 1, self.bounds().size.width, self.bounds().size.height - 2))

    def drawRect_(self, rect):
        NSColor.clearColor().setFill()
        NSBezierPath.fillRect_(rect)
        radius = rect.size.height / 2.0
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, radius, radius)
        self._color.colorWithAlphaComponent_(0.85).setFill()
        path.fill()


class _Sparkline(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(_Sparkline, self).initWithFrame_(frame)
        if self is None:
            return None
        self._values: list[float] = []
        self._color = NSColor.secondaryLabelColor()
        self.setWantsLayer_(True)
        return self

    def isOpaque(self):
        return False

    def applyValues_(self, values):
        self._values = list(values) if values else []
        self.setNeedsDisplay_(True)

    def applyColor_(self, color):
        self._color = color
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        NSColor.clearColor().setFill()
        NSBezierPath.fillRect_(rect)
        vals = self._values
        if len(vals) < 2 or rect.size.width <= 0 or rect.size.height <= 0:
            return
        lo = min(vals)
        hi = max(vals)
        span = hi - lo
        if span <= 0:
            span = 1.0
        n = len(vals)
        step = rect.size.width / (n - 1)
        path = NSBezierPath.alloc().init()
        for i, v in enumerate(vals):
            x = i * step
            y = rect.size.height - 2 - ((v - lo) / span) * (rect.size.height - 4)
            if i == 0:
                path.moveToPoint_(NSMakePoint(x, y))
            else:
                path.lineToPoint_(NSMakePoint(x, y))
        self._color.setStroke()
        path.setLineWidth_(1.5)
        path.stroke()


class _Action(NSObject):
    def initWithFn_(self, fn):
        self = objc.super(_Action, self).init()
        if self is None:
            return None
        self._fn = fn
        return self

    def run_(self, sender):
        self._fn()


class _SliderAction(NSObject):
    def initWithFn_(self, fn):
        self = objc.super(_SliderAction, self).init()
        if self is None:
            return None
        self._fn = fn
        return self

    def run_(self, sender):
        self._fn(sender.floatValue())


class PanelView(NSVisualEffectView):
    """Dark, rounded card holding the live system readout."""

    def initWithFrame_(self, frame):
        self = objc.super(PanelView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.setMaterial_(NSVisualEffectMaterialPopover)
        self.setState_(NSVisualEffectStateActive)
        self.setWantsLayer_(True)
        self.layer().setCornerRadius_(14)
        self._retain: list[Any] = []
        self._build()
        return self

    def isFlipped(self):
        return True

    @objc.python_method
    def _add(self, view, x, y, w, h):
        view.setFrame_(NSMakeRect(x, y, w, h))
        self.addSubview_(view)
        return view

    @objc.python_method
    def _build(self) -> None:
        pad = 16
        inner = WIDTH - pad * 2

        # Header
        self._title = self._add(_label("MacMedic", 16, NSColor.labelColor(), bold=True), pad, 14, 180, 22)
        self._health_pill = self._add(_Pill.alloc().initWithFrame_(NSZeroRect), pad + inner - 96, 12, 96, 24)

        # Tiles
        tile_y = 54
        tile_w = (inner - 2 * 8) / 3
        tile_labels = ["CPU", "GPU", "Fan"]
        self._tiles: list[dict] = []
        for i, name in enumerate(tile_labels):
            x = pad + i * (tile_w + 8)
            lab = self._add(_label(name, 11, NSColor.secondaryLabelColor()), x, tile_y, tile_w, 14)
            val = self._add(_label("—", 22, NSColor.labelColor(), bold=True), x, tile_y + 16, tile_w, 28)
            self._tiles.append({"label": lab, "value": val})

        # Section: Hardware
        sec_y = tile_y + 64 + 14
        self._add(_label("HARDWARE", 11, NSColor.secondaryLabelColor()), pad, sec_y, inner, 14)

        row1 = sec_y + 18
        self._add(_label("CPU", 12, NSColor.secondaryLabelColor()), pad, row1, 40, 16)
        self._cpu_pct = self._add(_label("0%", 12, NSColor.labelColor()), pad + inner - 48, row1, 48, 16)
        self._cpu_bar = self._add(_Bar.alloc().initWithFrame_(NSZeroRect), pad + 44, row1, inner - 44 - 52, 10)
        self._cpu_bar.applyColor_(NSColor.systemBlueColor())
        self._cpu_spark = self._add(
            _Sparkline.alloc().initWithFrame_(NSZeroRect), pad + 44, row1 + 14, inner - 44 - 52, 18
        )

        row2 = row1 + 40
        self._add(_label("Memory", 12, NSColor.secondaryLabelColor()), pad, row2, 56, 16)
        self._mem_pill = self._add(_Pill.alloc().initWithFrame_(NSZeroRect), pad + inner - 96, row2 - 2, 96, 20)
        self._mem_bar = self._add(_Bar.alloc().initWithFrame_(NSZeroRect), pad + 60, row2, inner - 60 - 104, 10)
        self._mem_bar.applyColor_(NSColor.systemIndigoColor())

        row3 = row2 + 34
        self._add(_label("Battery", 12, NSColor.secondaryLabelColor()), pad, row3, 60, 16)
        self._bat_pct = self._add(_label("0%", 12, NSColor.labelColor()), pad + inner - 48, row3, 48, 16)
        self._bat_bar = self._add(_Bar.alloc().initWithFrame_(NSZeroRect), pad + 64, row3, inner - 64 - 52, 10)
        self._bat_bar.applyColor_(NSColor.systemGreenColor())
        self._bat_info = self._add(_label("", 11, NSColor.secondaryLabelColor()), pad + 64, row3 + 14, inner - 64, 14)

        # Processes
        proc_y = row3 + 44
        self._add(_label("PROCESSES", 11, NSColor.secondaryLabelColor()), pad, proc_y, inner - 60, 14)
        self._proc_toggle = self._add(NSButton.alloc().initWithFrame_(NSZeroRect), pad + inner - 56, proc_y - 3, 56, 20)
        self._proc_toggle.setBezelStyle_(2)
        self._proc_toggle.setTitle_("CPU")
        self._proc_toggle.setTarget_(self)
        self._proc_toggle.setAction_("toggleProcMode:")
        scroll = NSScrollView.alloc().initWithFrame_(NSZeroRect)
        scroll.setHasVerticalScroller_(True)
        scroll.setHasHorizontalScroller_(False)
        scroll.setAutohidesScrollers_(True)
        scroll.setBorderType_(0)  # NSNoBorder
        scroll.setDrawsBackground_(False)
        self._proc_stack = NSStackView.alloc().initWithFrame_(NSMakeRect(0, 0, inner, 110))
        self._proc_stack.setOrientation_(1)  # vertical
        self._proc_stack.setSpacing_(4)
        scroll.setDocumentView_(self._proc_stack)
        self._add(scroll, pad, proc_y + 16, inner, 110)
        self._top_cpu: list[dict] = []
        self._top_mem: list[dict] = []
        self._proc_mode = "cpu"
        self._kill_cb = None
        self._proc_retain: list[Any] = []
        self._inner = inner

        # Fan
        fan_y = proc_y + 16 + 110 + 16
        self._add(_label("Fan", 12, NSColor.secondaryLabelColor()), pad, fan_y, 40, 16)
        self._fan_auto = self._add(NSButton.alloc().initWithFrame_(NSZeroRect), pad + inner - 56, fan_y - 3, 56, 22)
        self._fan_auto.setBezelStyle_(2)
        self._fan_auto.setTitle_("Auto")
        self._fan_slider = self._add(NSSlider.alloc().initWithFrame_(NSZeroRect), pad + 44, fan_y, inner - 44 - 64, 22)
        self._fan_slider.setMinValue_(1000.0)
        self._fan_slider.setMaxValue_(7000.0)
        self._fan_slider.setContinuous_(False)

        # Footer
        foot_y = fan_y + 40
        names = ["Sensors", "Clean", "Quit"]
        bw = (inner - 2 * 8) / 3
        self._foot: list[NSButton] = []
        for i, name in enumerate(names):
            x = pad + i * (bw + 8)
            btn = self._add(NSButton.alloc().initWithFrame_(NSZeroRect), x, foot_y, bw, 30)
            btn.setBezelStyle_(2)
            btn.setTitle_(name)
            self._foot.append(btn)

    @objc.python_method
    def applyFanRange_(self, lo, hi):
        self._fan_slider.setMinValue_(lo)
        self._fan_slider.setMaxValue_(hi)

    @objc.python_method
    def applyFanValue_(self, value):
        if value is not None:
            self._fan_slider.setFloatValue_(value)

    @objc.python_method
    def wire_callbacks(self, callbacks: dict) -> None:
        self._kill_cb = callbacks.get("kill_process")
        foot_actions = [callbacks.get("sensors"), callbacks.get("clean"), callbacks.get("quit")]
        for btn, fn in zip(self._foot, foot_actions):
            if fn is not None:
                holder = _Action.alloc().initWithFn_(fn)
                self._retain.append(holder)
                btn.setTarget_(holder)
                btn.setAction_("run:")
        auto_holder = _Action.alloc().initWithFn_(callbacks.get("fan_auto", lambda: None))
        self._retain.append(auto_holder)
        self._fan_auto.setTarget_(auto_holder)
        self._fan_auto.setAction_("run:")
        slider_holder = _SliderAction.alloc().initWithFn_(callbacks.get("fan_manual", lambda v: None))
        self._retain.append(slider_holder)
        self._fan_slider.setTarget_(slider_holder)
        self._fan_slider.setAction_("run:")

    @objc.python_method
    def update_processes(self, cpu_rows: list, mem_rows: list) -> None:
        self._top_cpu = list(cpu_rows)
        self._top_mem = list(mem_rows)
        self._render_proc_list()

    def toggleProcMode_(self, sender) -> None:
        self._proc_mode = "mem" if self._proc_mode == "cpu" else "cpu"
        self._proc_toggle.setTitle_(self._proc_mode.upper())
        self._render_proc_list()

    @objc.python_method
    def _render_proc_list(self) -> None:
        if self._proc_stack is None:
            return
        for v in list(self._proc_stack.subviews()):
            self._proc_stack.removeArrangedSubview_(v)
        self._proc_retain = []
        items = self._top_cpu if self._proc_mode == "cpu" else self._top_mem
        if not items:
            empty = _label("No data", 12, NSColor.secondaryLabelColor())
            empty.setFrame_(NSMakeRect(4, 4, self._inner - 8, 20))
            self._proc_stack.addArrangedSubview_(empty)
            return
        for item in items[:8]:
            self._proc_stack.addArrangedSubview_(self._make_proc_row(item))

    @objc.python_method
    def _make_proc_row(self, item: dict) -> NSView:
        name = item.get("name", "?")
        value = item.get("value", "")
        info = item.get("info")
        row = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, self._inner, 24))
        name_tf = _label(name, 12, NSColor.labelColor())
        name_tf.setFrame_(NSMakeRect(4, 3, self._inner - 92, 18))
        val_tf = _label(value, 12, NSColor.secondaryLabelColor())
        val_tf.setFrame_(NSMakeRect(self._inner - 88, 3, 52, 18))
        val_tf.setAlignment_(2)  # right
        btn = NSButton.alloc().initWithFrame_(NSMakeRect(self._inner - 32, 1, 28, 22))
        btn.setBezelStyle_(2)
        btn.setTitle_("✕")
        holder = _Action.alloc().initWithFn_(lambda i=info: self._kill_cb(i) if self._kill_cb else None)
        self._proc_retain.append(holder)
        btn.setTarget_(holder)
        btn.setAction_("run:")
        row.addSubview_(name_tf)
        row.addSubview_(val_tf)
        row.addSubview_(btn)
        return row

    @objc.python_method
    def update(self, state: dict) -> None:
        cpu_temp = state.get("cpu_temp")
        gpu_temp = state.get("gpu_temp")
        fan = state.get("fan_rpm")
        self._tiles[0]["value"].setStringValue_(f"{cpu_temp:.0f}°C" if cpu_temp is not None else "—")
        self._tiles[1]["value"].setStringValue_(f"{gpu_temp:.0f}°C" if gpu_temp is not None else "—")
        self._tiles[2]["value"].setStringValue_(f"{fan:.0f}" if fan is not None else "—")

        cpu_pct = state.get("cpu_pct", 0.0)
        mem_pct = state.get("mem_pct", 0.0)
        bat_pct = state.get("battery_pct")
        self._cpu_pct.setStringValue_(f"{cpu_pct:.0f}%")
        self._cpu_bar.applyProgress_(cpu_pct / 100.0)
        self._cpu_spark.applyValues_(state.get("cpu_history", []))
        self._mem_bar.applyProgress_(mem_pct / 100.0)
        self._bat_pct.setStringValue_(f"{bat_pct:.0f}%" if bat_pct is not None else "—")
        if bat_pct is not None:
            self._bat_bar.applyProgress_(bat_pct / 100.0)

        pressure = state.get("mem_pressure", 1)
        pcolor = {1: NSColor.systemGreenColor(), 2: NSColor.systemOrangeColor()}.get(pressure, NSColor.systemRedColor())
        plabel = {1: "Normal", 2: "Warning", 3: "Critical", 4: "Critical"}.get(pressure, "—")
        self._mem_pill.applyText_(f"● {plabel}")
        self._mem_pill.applyColor_(pcolor)

        health = state.get("health_pct")
        cycles = state.get("cycles")
        info = ""
        if health is not None:
            info += f"Health {health:.0f}%"
        if cycles is not None:
            info += f" · {cycles} cyc"
        self._bat_info.setStringValue_(info)

        score = state.get("health_score")
        if score is not None:
            scolor = (
                NSColor.systemGreenColor()
                if score >= 75
                else NSColor.systemOrangeColor()
                if score >= 50
                else NSColor.systemRedColor()
            )
            self._health_pill.applyText_(f"Health {score}/100")
            self._health_pill.applyColor_(scolor)
        else:
            self._health_pill.applyText_("Health —")
            self._health_pill.applyColor_(NSColor.secondaryLabelColor())


def build(callbacks: dict) -> tuple[PanelView, NSPopover]:
    view = PanelView.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, HEIGHT))
    view.wire_callbacks(callbacks)
    vc = NSViewController.alloc().init()
    vc.setView_(view)
    pop = NSPopover.alloc().init()
    pop.setContentViewController_(vc)
    pop.setContentSize_(view.frame().size)
    # Keep the panel pinned open when launched with the debug auto-open flag so
    # a screenshot tool can capture it without the transient popover dismissing.
    if os.environ.get("MACMEDIC_PANEL_AUTOOPEN"):
        pop.setBehavior_(NSPopoverBehaviorApplicationDefined)
    else:
        pop.setBehavior_(NSPopoverBehaviorTransient)
    pop.setAnimates_(True)
    return view, pop


def show_popover(pop: NSPopover, button: Any) -> None:
    if pop.isShown():
        pop.performClose_(None)
    else:
        pop.showRelativeToRect_ofView_preferredEdge_(NSZeroRect, button, NS_RECT_EDGE_MIN_Y)


def close_popover(pop: NSPopover) -> None:
    if pop.isShown():
        pop.performClose_(None)
