# -*- coding: utf-8 -*-
"""The Settings window, built in code (no nib files to go stale).

Changes apply immediately - there is no Save button - because the frame is
usually being adjusted while it is running.
"""

from __future__ import print_function

import AppKit
from AppKit import (
    NSApp, NSBackingStoreBuffered, NSBox, NSButton, NSColor, NSFont, NSOpenPanel,
    NSPopUpButton, NSStepper, NSTextField, NSView, NSWindow,
)
from Foundation import NSMakeRect, NSObject, NSURL

import pf_config
import pf_system

try:  # PyObjC 4+ wants its own super() inside Objective-C subclasses
    from objc import super       # noqa: A004
except ImportError:              # the PyObjC bundled with 10.13 has no objc.super
    pass

# Enum values that were renamed between the 10.13-era and modern SDKs.
STYLE_TITLED = getattr(AppKit, "NSWindowStyleMaskTitled", 1)
STYLE_CLOSABLE = getattr(AppKit, "NSWindowStyleMaskClosable", 2)
BUTTON_SWITCH = getattr(AppKit, "NSButtonTypeSwitch", 3)
BEZEL_ROUNDED = getattr(AppKit, "NSBezelStyleRounded", 1)
BOX_SEPARATOR = getattr(AppKit, "NSBoxSeparator", 2)

WINDOW_WIDTH = 640.0
MARGIN = 26.0
ROW = 26.0
GAP = 12.0

ORDER_ITEMS = [
    (u"True random (every photo equally likely, every time)", "true_random"),
    (u"Shuffle (show every photo once, then reshuffle)", "shuffle"),
]

DATE_ITEMS = [
    (u"12 August 2009", "long"),
    (u"12 Aug 2009", "medium"),
    (u"August 2009", "month_year"),
    (u"2009-08-12", "iso"),
    (u"2009", "year"),
]


LINE_BREAK_WRAP = 0
LINE_BREAK_TRUNCATE_MIDDLE = 5


def _label(text, frame, bold=False, size=13.0, color=None, align=None,
           wrap=False, line_break=None):
    field = NSTextField.alloc().initWithFrame_(frame)
    field.setStringValue_(text)
    field.setBezeled_(False)
    field.setDrawsBackground_(False)
    field.setEditable_(False)
    field.setSelectable_(False)
    field.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    field.setTextColor_(color or NSColor.labelColor())
    if align is not None:
        field.setAlignment_(align)
    if wrap:
        field.setUsesSingleLineMode_(False)
        field.cell().setWraps_(True)
        field.cell().setLineBreakMode_(LINE_BREAK_WRAP)
    elif line_break is not None:
        field.cell().setLineBreakMode_(line_break)
    return field


def _field(text, frame, controller, action=b"valueEdited:"):
    field = NSTextField.alloc().initWithFrame_(frame)
    field.setStringValue_(text)
    field.setTarget_(controller)
    field.setAction_(action)
    return field


def _check(title, on, frame, controller, action=b"valueEdited:"):
    button = NSButton.alloc().initWithFrame_(frame)
    button.setButtonType_(BUTTON_SWITCH)
    button.setTitle_(title)
    button.setState_(1 if on else 0)
    button.setTarget_(controller)
    button.setAction_(action)
    return button


def _push(title, frame, controller, action):
    button = NSButton.alloc().initWithFrame_(frame)
    button.setBezelStyle_(BEZEL_ROUNDED)
    button.setTitle_(title)
    button.setTarget_(controller)
    button.setAction_(action)
    return button


def _popup(items, selected_value, frame, controller, action=b"valueEdited:"):
    popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(frame, False)
    popup.addItemsWithTitles_([title for title, _ in items])
    for index, pair in enumerate(items):
        if pair[1] == selected_value:
            popup.selectItemAtIndex_(index)
            break
    popup.setTarget_(controller)
    popup.setAction_(action)
    return popup


def _stepper(value, low, high, step, frame, controller, action=b"stepperMoved:"):
    stepper = NSStepper.alloc().initWithFrame_(frame)
    stepper.setMinValue_(low)
    stepper.setMaxValue_(high)
    stepper.setIncrement_(step)
    stepper.setDoubleValue_(value)
    stepper.setValueWraps_(False)
    stepper.setTarget_(controller)
    stepper.setAction_(action)
    return stepper


class _Layout(object):
    """Places controls from the top down; converts to AppKit's bottom-up frames."""

    def __init__(self, width):
        self.width = width
        self.y = MARGIN
        self.views = []

    def rect(self, x, w, h, dy=0.0):
        return (x, self.y + dy, w, h)

    def add(self, view_factory, x, w, h, dy=0.0, advance=None):
        placeholder = (x, self.y + dy, w, h)
        view = view_factory(placeholder)
        self.views.append((view, placeholder))
        if advance is not None:
            self.y += advance
        return view

    def space(self, amount):
        self.y += amount

    def finish(self, container_height):
        for view, (x, top, w, h) in self.views:
            view.setFrame_(NSMakeRect(x, container_height - top - h, w, h))


class SettingsController(NSObject):

    def initWithDelegate_(self, delegate):
        self = super(SettingsController, self).init()
        if self is None:
            return None
        self.delegate = delegate
        self.cfg = pf_config.load()
        self.controls = {}
        self.window = None
        self._suspend = False
        self._buildWindow()
        return self

    # -- construction ----------------------------------------------------
    def _buildWindow(self):
        cfg = self.cfg
        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, WINDOW_WIDTH, 100))
        L = _Layout(WINDOW_WIDTH)
        full = WINDOW_WIDTH - 2 * MARGIN
        right_col = MARGIN + 150.0

        def header(text):
            L.add(lambda f: _label(text, NSMakeRect(*f), bold=True, size=11.0,
                                   color=NSColor.secondaryLabelColor()),
                  MARGIN, full, 16.0, advance=20.0)

        def note(text, lines=1):
            height = 14.0 * lines + 2.0
            L.add(lambda f: _label(text, NSMakeRect(*f), size=11.0,
                                   color=NSColor.secondaryLabelColor(), wrap=True),
                  MARGIN, full, height, advance=height + 4.0)

        def rule():
            L.space(6.0)
            L.add(lambda f: self.makeSeparator_(f), MARGIN, full, 1.0, advance=16.0)

        # -- Photos ------------------------------------------------------
        header(u"PHOTOS")
        self.controls["folder"] = L.add(
            lambda f: _label(cfg["folder"] or u"No folder chosen yet", NSMakeRect(*f), size=13.0,
                             line_break=LINE_BREAK_TRUNCATE_MIDDLE),
            MARGIN, full - 150.0, ROW)
        L.add(lambda f: _push(u"Choose Folder…", NSMakeRect(*f), self, b"chooseFolder:"),
              MARGIN + full - 145.0, 145.0, ROW, dy=-3.0, advance=ROW + 4.0)
        self.controls["library_status"] = L.add(
            lambda f: _label(u"", NSMakeRect(*f), size=11.0, color=NSColor.secondaryLabelColor()),
            MARGIN, full - 130.0, 16.0)
        L.add(lambda f: _push(u"Rescan Now", NSMakeRect(*f), self, b"rescanNow:"),
              MARGIN + full - 125.0, 125.0, ROW, dy=-6.0, advance=ROW + 2.0)
        note(u"Every sub-folder is searched. JPEG, PNG, HEIC, TIFF, GIF and common raw files are included.")
        rule()

        # -- Playback ----------------------------------------------------
        header(u"PLAYBACK")
        L.add(lambda f: _label(u"Seconds per photo", NSMakeRect(*f)), MARGIN, 140.0, ROW, dy=2.0)
        self.controls["seconds"] = L.add(
            lambda f: _field(u"%g" % cfg["seconds_per_photo"], NSMakeRect(*f), self),
            right_col, 70.0, 22.0, dy=2.0)
        self.controls["seconds_stepper"] = L.add(
            lambda f: _stepper(cfg["seconds_per_photo"], 1, 3600, 5, NSMakeRect(*f), self),
            right_col + 74.0, 17.0, 24.0, dy=1.0, advance=ROW + 6.0)

        L.add(lambda f: _label(u"Cross-fade (seconds)", NSMakeRect(*f)), MARGIN, 140.0, ROW, dy=2.0)
        self.controls["fade"] = L.add(
            lambda f: _field(u"%g" % cfg["fade_seconds"], NSMakeRect(*f), self),
            right_col, 70.0, 22.0, dy=2.0)
        self.controls["fade_stepper"] = L.add(
            lambda f: _stepper(cfg["fade_seconds"], 0, 10, 0.5, NSMakeRect(*f), self),
            right_col + 74.0, 17.0, 24.0, dy=1.0, advance=ROW + 6.0)

        L.add(lambda f: _label(u"Order", NSMakeRect(*f)), MARGIN, 140.0, ROW, dy=2.0)
        self.controls["order"] = L.add(
            lambda f: _popup(ORDER_ITEMS, cfg["random_mode"], NSMakeRect(*f), self),
            right_col, full - (right_col - MARGIN), 26.0, advance=ROW + 8.0)

        L.add(lambda f: _label(u"Avoid repeats within", NSMakeRect(*f)), MARGIN, 140.0, ROW, dy=2.0)
        self.controls["window"] = L.add(
            lambda f: _field(u"%d" % cfg["no_repeat_window"], NSMakeRect(*f), self),
            right_col, 70.0, 22.0, dy=2.0)
        self.controls["window_label"] = L.add(
            lambda f: _label(u"photos", NSMakeRect(*f)), right_col + 78.0, 200.0, ROW,
            dy=2.0, advance=ROW + 2.0)
        note(u"True random draws from the whole library every time, so a photo can reappear; "
             u"the repeat window keeps that from happening too soon.", lines=2)
        rule()

        # -- Caption -----------------------------------------------------
        header(u"DATE CAPTION")
        self.controls["show_date"] = L.add(
            lambda f: _check(u"Show each photo's date in the bottom-right corner",
                             cfg["show_date"], NSMakeRect(*f), self),
            MARGIN, full, ROW, advance=ROW + 4.0)
        L.add(lambda f: _label(u"Style", NSMakeRect(*f)), MARGIN, 140.0, ROW, dy=2.0)
        self.controls["date_format"] = L.add(
            lambda f: _popup(DATE_ITEMS, cfg["date_format"], NSMakeRect(*f), self),
            right_col, 200.0, 26.0)
        L.add(lambda f: _label(u"Size", NSMakeRect(*f)), right_col + 216.0, 40.0, ROW, dy=2.0)
        self.controls["caption_size"] = L.add(
            lambda f: _field(u"%d" % cfg["caption_size"], NSMakeRect(*f), self),
            right_col + 256.0, 50.0, 22.0, dy=2.0)
        self.controls["caption_stepper"] = L.add(
            lambda f: _stepper(cfg["caption_size"], 10, 96, 2, NSMakeRect(*f), self),
            right_col + 310.0, 17.0, 24.0, dy=1.0, advance=ROW + 6.0)
        note(u"The date comes from the photo's EXIF data, or from the file's date when there is none.")
        rule()

        # -- Schedule ----------------------------------------------------
        header(u"DAILY SCHEDULE")
        self.controls["schedule"] = L.add(
            lambda f: _check(u"Run only between the times below", cfg["schedule_enabled"],
                             NSMakeRect(*f), self),
            MARGIN, full, ROW, advance=ROW + 4.0)
        L.add(lambda f: _label(u"On at", NSMakeRect(*f)), MARGIN, 60.0, ROW, dy=2.0)
        self.controls["start_time"] = L.add(
            lambda f: _field(cfg["start_time"], NSMakeRect(*f), self), MARGIN + 60.0, 70.0, 22.0, dy=2.0)
        L.add(lambda f: _label(u"Off at", NSMakeRect(*f)), MARGIN + 150.0, 60.0, ROW, dy=2.0)
        self.controls["end_time"] = L.add(
            lambda f: _field(cfg["end_time"], NSMakeRect(*f), self), MARGIN + 210.0, 70.0, 22.0, dy=2.0)
        L.add(lambda f: _label(u"24-hour clock", NSMakeRect(*f), size=11.0,
                               color=NSColor.secondaryLabelColor()),
              MARGIN + 290.0, 150.0, ROW, dy=3.0, advance=ROW + 6.0)

        self.controls["sleep"] = L.add(
            lambda f: _check(u"Put the Mac to sleep while the frame is off",
                             cfg["sleep_when_off"], NSMakeRect(*f), self),
            MARGIN, full, ROW, advance=ROW + 6.0)

        L.add(lambda f: _push(u"Wake the Mac Automatically…", NSMakeRect(*f), self, b"installWake:"),
              MARGIN, 230.0, ROW)
        L.add(lambda f: _push(u"Remove Wake Schedule", NSMakeRect(*f), self, b"removeWake:"),
              MARGIN + 238.0, 190.0, ROW, advance=ROW + 4.0)
        self.controls["wake_status"] = L.add(
            lambda f: _label(u"", NSMakeRect(*f), size=11.0, color=NSColor.secondaryLabelColor()),
            MARGIN, full, 16.0, advance=20.0)
        note(u"Sleeping is done by Photo Frame; waking has to be set in the Mac's power "
             u"settings, which needs your password once.", lines=2)
        rule()

        # -- Startup -----------------------------------------------------
        header(u"STARTUP")
        self.controls["login_item"] = L.add(
            lambda f: _check(u"Open Photo Frame automatically when this Mac starts up",
                             False, NSMakeRect(*f), self, b"toggleLoginItem:"),
            MARGIN, full, ROW, advance=ROW + 4.0)
        self.controls["screen_saver"] = L.add(
            lambda f: _check(u"Keep the screen saver from covering the photos",
                             cfg["manage_screen_saver"], NSMakeRect(*f), self),
            MARGIN, full, ROW, advance=ROW + 10.0)

        rule()
        L.add(lambda f: _push(u"Quit Photo Frame", NSMakeRect(*f), self, b"quitApp:"),
              MARGIN, 160.0, 30.0)
        done = L.add(lambda f: _push(u"Done", NSMakeRect(*f), self, b"done:"),
                     MARGIN + full - 110.0, 110.0, 30.0, advance=30.0 + MARGIN)

        height = L.y
        content.setFrame_(NSMakeRect(0, 0, WINDOW_WIDTH, height))
        L.finish(height)
        for view, _frame in L.views:
            content.addSubview_(view)

        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WINDOW_WIDTH, height), STYLE_TITLED | STYLE_CLOSABLE,
            NSBackingStoreBuffered, False)
        window.setTitle_(u"Photo Frame Settings")
        window.setContentView_(content)
        window.setDelegate_(self)
        window.setReleasedWhenClosed_(False)
        window.setDefaultButtonCell_(done.cell())
        window.center()
        self.window = window

        self._pairs = [
            ("seconds", "seconds_stepper"),
            ("fade", "fade_stepper"),
            ("caption_size", "caption_stepper"),
        ]
        self.refreshEnabled()
        self.refreshWakeStatus()
        self.refreshLoginItem()

    def makeSeparator_(self, frame):
        box = NSBox.alloc().initWithFrame_(NSMakeRect(*frame))
        box.setBoxType_(BOX_SEPARATOR)
        return box

    # -- window ----------------------------------------------------------
    def showWindow(self):
        self.cfg = pf_config.load()
        self._loadIntoControls()
        self.refreshWakeStatus()
        self.refreshLoginItem()
        self.window.setLevel_(26)
        self.window.makeKeyAndOrderFront_(None)
        NSApp().activateIgnoringOtherApps_(True)
        self.delegate.settingsWindowOpened()

    def windowWillClose_(self, notification):
        self.applyChanges()
        self.delegate.settingsWindowClosed()

    def isVisible(self):
        return bool(self.window is not None and self.window.isVisible())

    # -- state <-> controls ---------------------------------------------
    def _loadIntoControls(self):
        cfg = self.cfg
        self._suspend = True
        c = self.controls
        c["folder"].setStringValue_(cfg["folder"] or u"No folder chosen yet")
        c["seconds"].setStringValue_(u"%g" % cfg["seconds_per_photo"])
        c["seconds_stepper"].setDoubleValue_(cfg["seconds_per_photo"])
        c["fade"].setStringValue_(u"%g" % cfg["fade_seconds"])
        c["fade_stepper"].setDoubleValue_(cfg["fade_seconds"])
        c["window"].setStringValue_(u"%d" % cfg["no_repeat_window"])
        c["caption_size"].setStringValue_(u"%d" % cfg["caption_size"])
        c["caption_stepper"].setDoubleValue_(cfg["caption_size"])
        c["show_date"].setState_(1 if cfg["show_date"] else 0)
        c["schedule"].setState_(1 if cfg["schedule_enabled"] else 0)
        c["sleep"].setState_(1 if cfg["sleep_when_off"] else 0)
        c["screen_saver"].setState_(1 if cfg["manage_screen_saver"] else 0)
        c["start_time"].setStringValue_(cfg["start_time"])
        c["end_time"].setStringValue_(cfg["end_time"])
        for key, items in (("order", ORDER_ITEMS), ("date_format", DATE_ITEMS)):
            value = cfg["random_mode"] if key == "order" else cfg["date_format"]
            for index, pair in enumerate(items):
                if pair[1] == value:
                    c[key].selectItemAtIndex_(index)
                    break
        self._suspend = False
        self.refreshEnabled()

    def _readControls(self):
        c = self.controls
        cfg = dict(self.cfg)
        cfg["seconds_per_photo"] = _to_float(c["seconds"].stringValue(), cfg["seconds_per_photo"])
        cfg["fade_seconds"] = _to_float(c["fade"].stringValue(), cfg["fade_seconds"])
        cfg["no_repeat_window"] = _to_float(c["window"].stringValue(), cfg["no_repeat_window"])
        cfg["caption_size"] = _to_float(c["caption_size"].stringValue(), cfg["caption_size"])
        cfg["show_date"] = bool(c["show_date"].state())
        cfg["schedule_enabled"] = bool(c["schedule"].state())
        cfg["sleep_when_off"] = bool(c["sleep"].state())
        cfg["manage_screen_saver"] = bool(c["screen_saver"].state())
        cfg["start_time"] = c["start_time"].stringValue()
        cfg["end_time"] = c["end_time"].stringValue()
        cfg["random_mode"] = ORDER_ITEMS[max(0, c["order"].indexOfSelectedItem())][1]
        cfg["date_format"] = DATE_ITEMS[max(0, c["date_format"].indexOfSelectedItem())][1]
        return pf_config.sanitize(cfg)

    def applyChanges(self):
        if self._suspend:
            return
        self.cfg = pf_config.save(self._readControls())
        self._suspend = True
        self._loadIntoControls()   # echo back the sanitized values
        self._suspend = False
        self.refreshEnabled()
        self.delegate.settingsChanged_(self.cfg)

    def refreshEnabled(self):
        c = self.controls
        true_random = c["order"].indexOfSelectedItem() == 0
        c["window"].setEnabled_(true_random)
        c["window_label"].setTextColor_(
            NSColor.labelColor() if true_random else NSColor.disabledControlTextColor())
        scheduled = bool(c["schedule"].state())
        for key in ("start_time", "end_time", "sleep"):
            c[key].setEnabled_(scheduled)
        shows_date = bool(c["show_date"].state())
        for key in ("date_format", "caption_size", "caption_stepper"):
            c[key].setEnabled_(shows_date)

    def refreshWakeStatus(self):
        self.controls["wake_status"].setStringValue_(pf_system.wake_schedule_summary())

    def refreshLoginItem(self):
        path = pf_system.app_bundle_path()
        button = self.controls["login_item"]
        if not path:
            button.setEnabled_(False)
            button.setState_(0)
            button.setTitle_(u"Open automatically at startup (install the app first - see the Read Me)")
            return
        button.setEnabled_(True)
        button.setState_(1 if pf_system.login_item_enabled(path) else 0)

    def updateLibraryStatus_(self, text):
        if self.controls.get("library_status") is not None:
            self.controls["library_status"].setStringValue_(text or u"")

    # -- actions ---------------------------------------------------------
    def valueEdited_(self, sender):
        self.applyChanges()

    def stepperMoved_(self, sender):
        for field_key, stepper_key in self._pairs:
            if self.controls[stepper_key] is sender:
                value = sender.doubleValue()
                text = u"%d" % int(value) if field_key == "caption_size" else u"%g" % value
                self.controls[field_key].setStringValue_(text)
        self.applyChanges()

    def chooseFolder_(self, sender):
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(False)
        panel.setCanChooseDirectories_(True)
        panel.setAllowsMultipleSelection_(False)
        panel.setResolvesAliases_(True)
        panel.setPrompt_(u"Use This Folder")
        panel.setMessage_(u"Choose the folder that holds your photos. Sub-folders are included.")
        if self.cfg.get("folder"):
            panel.setDirectoryURL_(NSURL.fileURLWithPath_(self.cfg["folder"]))
        if panel.runModal() != 1:
            return
        urls = panel.URLs()
        if not urls:
            return
        self.cfg["folder"] = urls[0].path()
        self.controls["folder"].setStringValue_(self.cfg["folder"])
        self.cfg = pf_config.save(self.cfg)
        self.delegate.settingsChanged_(self.cfg)
        self.delegate.rescanRequested()

    def rescanNow_(self, sender):
        self.applyChanges()
        self.delegate.rescanRequested()

    def installWake_(self, sender):
        self.applyChanges()
        ok, message = pf_system.install_wake_schedule(self.cfg["start_time"])
        self.refreshWakeStatus()
        if not ok:
            _alert(u"Could not set the wake schedule", message)

    def removeWake_(self, sender):
        ok, message = pf_system.remove_wake_schedule()
        self.refreshWakeStatus()
        if not ok:
            _alert(u"Could not remove the wake schedule", message)

    def toggleLoginItem_(self, sender):
        wanted = bool(sender.state())
        ok, message = pf_system.set_login_item(wanted, pf_system.app_bundle_path())
        if not ok:
            sender.setState_(0 if wanted else 1)
            _alert(u"Could not change the startup setting", message)

    def done_(self, sender):
        self.window.performClose_(None)

    def quitApp_(self, sender):
        self.applyChanges()
        NSApp().terminate_(None)


def _to_float(text, fallback):
    try:
        return float(u"%s" % text.strip().replace(u",", u"."))
    except (ValueError, AttributeError):
        return fallback


def _alert(title, message):
    alert = AppKit.NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.setInformativeText_(message or u"")
    alert.addButtonWithTitle_(u"OK")
    alert.runModal()
