#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Photo Frame - a full-screen random slideshow for an always-on Mac.

Built against the Python + PyObjC that ships with macOS 10.13 High Sierra,
so there is nothing to install on the frame machine. Also runs on Python 3
with PyObjC installed, which is how it is developed and tested.

    python photoframe.py
"""

from __future__ import print_function

import os
import sys
import threading
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:                     # Python 2 on the frame, Python 3 everywhere else
    import Queue as queue
except ImportError:
    import queue

import AppKit
from AppKit import (
    NSApplication, NSApp, NSMenu, NSMenuItem, NSWorkspace, NSCursor,
)
from Foundation import (
    NSAutoreleasePool, NSNotificationCenter, NSObject, NSRunLoop, NSThread, NSTimer,
)

import pf_config
import pf_image
import pf_index
import pf_settings
import pf_slideshow
import pf_system

try:  # PyObjC 4+ wants its own super() inside Objective-C subclasses
    from objc import super       # noqa: A004
except ImportError:              # the PyObjC bundled with 10.13 has no objc.super
    pass

ACTIVATION_REGULAR = getattr(AppKit, "NSApplicationActivationPolicyRegular", 0)
SCHEDULE_TICK_SECONDS = 20.0
HINT_TEXT = (u"Esc = settings    Space = pause    ← → = back / forward    "
             u"D = hide the date    Cmd-Q = quit")

KEY_ESCAPE = 53
KEY_LEFT = 123
KEY_RIGHT = 124
KEY_SPACE = 49


def log(message):
    line = u"%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), message)
    try:
        print(line)
    except Exception:
        pass
    try:
        with open(pf_config.log_path(), "ab") as handle:
            handle.write((line + u"\n").encode("utf-8"))
    except Exception:
        pass


def _minutes(hhmm):
    hh, mm = pf_config.parse_hhmm(hhmm)
    return hh * 60 + mm


def within_schedule(cfg, now=None):
    """Is the frame meant to be showing photos right now?"""
    if not cfg.get("schedule_enabled"):
        return True
    now = now or time.localtime()
    current = now.tm_hour * 60 + now.tm_min
    start = _minutes(cfg["start_time"])
    end = _minutes(cfg["end_time"])
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end       # spans midnight


class AppDelegate(NSObject):

    # -- lifecycle -------------------------------------------------------
    def init(self):
        self = super(AppDelegate, self).init()
        if self is None:
            return None

        self.cfg = pf_config.load()
        self.slideshow = None
        self.settings = None
        self.caffeinator = pf_system.Caffeinator()
        self.picker = pf_index.Picker(
            [], self.cfg["random_mode"], self.cfg["no_repeat_window"])

        self.showing = False          # slideshow window up and advancing
        self.paused = False
        self.currentPath = None
        self.currentDate = None
        self.advanceTimer = None
        self.scheduleTimer = None
        self.hintTimer = None

        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._results = []
        self._displayToken = 0
        self._preloaded = None        # (path, CGImage, datetime)
        self._failStreak = 0

        self._scanning = False
        self._scanStop = False
        self._scanCount = 0
        self._scanPaths = None
        self._lastScan = 0.0
        self._sleepDeferUntil = 0.0
        return self

    def applicationDidFinishLaunching_(self, notification):
        NSApp().setActivationPolicy_(ACTIVATION_REGULAR)
        self._buildMenu()

        # Tell Cocoa we are about to use threads before any of them start.
        NSThread.detachNewThreadSelector_toTarget_withObject_(b"noop", self, None)

        self.slideshow = pf_slideshow.SlideshowController.alloc().initWithDelegate_(self)
        self.settings = pf_settings.SettingsController.alloc().initWithDelegate_(self)
        self.applyLookSettings()

        worker = threading.Thread(target=self._workerLoop)
        worker.daemon = True
        worker.start()

        NSWorkspace.sharedWorkspace().notificationCenter().addObserver_selector_name_object_(
            self, b"systemDidWake:", "NSWorkspaceDidWakeNotification", None)
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, b"screensChanged:", "NSApplicationDidChangeScreenParametersNotification", None)

        self.applyScreenSaverSetting()

        cached, scanned_at = pf_index.load_index(self.cfg["folder"])
        if cached:
            self.picker.set_paths(cached)
            self._lastScan = scanned_at
            log(u"Loaded %d photos from the cached index." % len(cached))

        self.scheduleTimer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            SCHEDULE_TICK_SECONDS, self, b"scheduleTick:", None, True)
        NSRunLoop.currentRunLoop().addTimer_forMode_(
            self.scheduleTimer, getattr(AppKit, "NSEventTrackingRunLoopMode", "NSEventTrackingRunLoopMode"))

        if not self.cfg["folder"]:
            self.startShow()
            self.slideshow.view.setStatus_(
                u"Welcome to Photo Frame\n\nChoose the folder that holds your photos.")
            self.openSettings()
        else:
            self.evaluateSchedule()
            self.startScanForced_(False)

    def applicationShouldTerminateAfterLastWindowClosed_(self, app):
        return False

    def applicationWillTerminate_(self, notification):
        self._scanStop = True
        self.caffeinator.stop()
        try:
            self._queue.put(None)
        except Exception:
            pass

    def noop(self):
        return None

    def _buildMenu(self):
        menubar = NSMenu.alloc().init()
        app_item = NSMenuItem.alloc().init()
        menubar.addItem_(app_item)
        NSApp().setMainMenu_(menubar)

        app_menu = NSMenu.alloc().init()
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            u"Settings…", b"openSettingsMenu:", u",")
        item.setTarget_(self)
        app_menu.addItem_(item)
        app_menu.addItem_(NSMenuItem.separatorItem())
        app_menu.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            u"Hide Photo Frame", b"hide:", u"h"))
        app_menu.addItem_(NSMenuItem.separatorItem())
        app_menu.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            u"Quit Photo Frame", b"terminate:", u"q"))
        app_item.setSubmenu_(app_menu)

        show_item = NSMenuItem.alloc().init()
        menubar.addItem_(show_item)
        show_menu = NSMenu.alloc().initWithTitle_(u"Slideshow")
        for title, selector, key in (
                (u"Next Photo", b"menuNext:", u"]"),
                (u"Previous Photo", b"menuPrevious:", u"["),
                (u"Pause / Resume", b"menuPause:", u"p"),
                (u"Rescan Folder", b"menuRescan:", u"r")):
            entry = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, selector, key)
            entry.setTarget_(self)
            show_menu.addItem_(entry)
        show_item.setSubmenu_(show_menu)

    # -- settings plumbing ------------------------------------------------
    def openSettings(self):
        self.settings.showWindow()
        self.updateLibraryStatus()

    def openSettingsMenu_(self, sender):
        self.openSettings()

    def settingsWindowOpened(self):
        if self.slideshow is not None:
            self.slideshow.elevate_(False)
        NSCursor.unhide()

    def settingsWindowClosed(self):
        if self.slideshow is not None and self.showing:
            self.slideshow.elevate_(True)
        self.evaluateSchedule()

    def settingsChanged_(self, cfg):
        old = self.cfg
        self.cfg = cfg
        self.picker.set_mode(cfg["random_mode"], cfg["no_repeat_window"])
        self.applyLookSettings()

        if cfg["folder"] != old["folder"]:
            self.picker.set_paths([])
            self._preloaded = None
            self.currentPath = None
            cached, scanned_at = pf_index.load_index(cfg["folder"])
            if cached:
                self.picker.set_paths(cached)
                self._lastScan = scanned_at
        if abs(cfg["seconds_per_photo"] - old["seconds_per_photo"]) > 0.001 and self.showing:
            self.restartAdvanceTimer()
        if cfg["manage_screen_saver"] != old["manage_screen_saver"]:
            self.applyScreenSaverSetting()
        self.evaluateSchedule()

    def applyScreenSaverSetting(self):
        """Only touches the Mac's setting when it does not already match."""
        wanted = bool(self.cfg["manage_screen_saver"])
        if wanted == pf_system.screen_saver_disabled():
            return
        if pf_system.set_screen_saver_disabled(wanted):
            log(u"Screen saver %s." %
                (u"turned off so it cannot cover the photos" if wanted
                 else u"put back to the Mac's own default"))

    def applyLookSettings(self):
        view = self.slideshow.view
        view.setFadeSeconds_(self.cfg["fade_seconds"])
        view.setCaptionSize_(self.cfg["caption_size"])
        view.setCaption_(self.captionText())

    def captionText(self):
        if not self.cfg["show_date"]:
            return u""
        return pf_image.format_date(self.currentDate, self.cfg["date_format"])

    def updateLibraryStatus(self):
        count = self.picker.count()
        if self._scanning:
            text = u"Scanning… %s photos found so far" % _thousands(self._scanCount)
        elif count:
            text = u"%s photos" % _thousands(count)
            if self._lastScan:
                text += u" · last scanned %s" % time.strftime(
                    "%d %b %Y at %H:%M", time.localtime(self._lastScan))
        elif self.cfg["folder"]:
            text = u"No photos found in that folder."
        else:
            text = u"No folder chosen yet."
        if self.settings is not None:
            self.settings.updateLibraryStatus_(text)

    # -- scanning ---------------------------------------------------------
    def rescanRequested(self):
        self.startScanForced_(True)

    def startScanForced_(self, force):
        folder = self.cfg["folder"]
        if not folder or self._scanning:
            return
        if not force and self.picker.count():
            age_hours = (time.time() - self._lastScan) / 3600.0
            if self.cfg["rescan_hours"] and age_hours < self.cfg["rescan_hours"]:
                self.updateLibraryStatus()
                return
        self._scanning = True
        self._scanStop = False
        self._scanCount = 0
        self.updateLibraryStatus()
        thread = threading.Thread(target=self.scanLoop_, args=(folder,))
        thread.daemon = True
        thread.start()

    def scanLoop_(self, folder):
        try:
            paths = pf_index.scan(
                folder,
                should_stop=lambda: self._scanStop,
                progress=self.reportScanProgress_)
        except Exception:
            log(u"Scan failed:\n" + traceback.format_exc())
            paths = []
        self._scanPaths = paths
        self.performSelectorOnMainThread_withObject_waitUntilDone_(b"scanFinished:", None, False)

    def reportScanProgress_(self, count):
        self._scanCount = count
        self.performSelectorOnMainThread_withObject_waitUntilDone_(b"scanProgress:", None, False)

    def scanProgress_(self, _ignored):
        self.updateLibraryStatus()
        if self.showing and not self.currentPath:
            self.slideshow.view.setStatus_(
                u"Looking for photos…\n%s found so far" % _thousands(self._scanCount))

    def scanFinished_(self, _ignored):
        paths = self._scanPaths or []
        self._scanning = False
        self._scanPaths = None
        if paths:
            self.picker.set_paths(paths)
            self._lastScan = time.time()
            pf_index.save_index(self.cfg["folder"], paths)
            log(u"Scan complete: %d photos." % len(paths))
        else:
            log(u"Scan found no photos in %s" % self.cfg["folder"])
        self.updateLibraryStatus()

        if self.showing:
            if not paths:
                self.slideshow.view.setStatus_(
                    u"No photos found in\n%s\n\nPress Esc to choose a different folder."
                    % (self.cfg["folder"] or u"(no folder)"))
            elif not self.currentPath:
                self.slideshow.view.setStatus_(u"")
                self.advance_(1)

    # -- the show ---------------------------------------------------------
    def startShow(self):
        if self.showing:
            return
        self.showing = True
        self.paused = False
        self.caffeinator.start()
        pf_system.wake_display()
        self.slideshow.show()
        self.slideshow.view.setHint_(HINT_TEXT)
        if self.hintTimer is not None:
            self.hintTimer.invalidate()
        self.hintTimer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            pf_slideshow.HINT_SECONDS, self, b"hideHint:", None, False)
        log(u"Slideshow on.")

        if self.picker.count():
            self.slideshow.view.setStatus_(u"")
            self.advance_(1)
        elif self.cfg["folder"]:
            self.slideshow.view.setStatus_(u"Looking for photos…")
            self.startScanForced_(False)
        self.restartAdvanceTimer()

    def stopShow(self):
        if not self.showing:
            return
        self.showing = False
        self.stopAdvanceTimer()
        self.caffeinator.stop()
        self.slideshow.hide()
        log(u"Slideshow off.")

    def hideHint_(self, timer):
        self.hintTimer = None
        self.slideshow.view.fadeHintOut()

    def restartAdvanceTimer(self):
        self.stopAdvanceTimer()
        if self.paused or not self.showing:
            return
        self.advanceTimer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            self.cfg["seconds_per_photo"], self, b"advanceTimerFired:", None, True)

    def stopAdvanceTimer(self):
        if self.advanceTimer is not None:
            self.advanceTimer.invalidate()
            self.advanceTimer = None

    def advanceTimerFired_(self, timer):
        self.advance_(1)

    def advance_(self, direction):
        """direction: 1 forwards, -1 backwards."""
        if not self.picker.count():
            return
        if direction < 0:
            path = self.picker.previous()
            if path is None:
                return
        else:
            path = self.picker.next()
            if path is None:
                return

        if (self._preloaded is not None and self._preloaded[0] == path
                and self._preloaded[1] is not None):
            path, image, when = self._preloaded
            self._preloaded = None
            self.displayPath_image_date_(path, image, when)
            return

        self._preloaded = None
        self._displayToken += 1
        self._queue.put(("display", self._displayToken, path, self.slideshow.maxPixelSize()))

    def displayPath_image_date_(self, path, image, when):
        self._failStreak = 0
        self.currentPath = path
        self.currentDate = when
        self.slideshow.view.setStatus_(u"")
        self.slideshow.view.showImage_caption_(image, self.captionText())
        NSCursor.setHiddenUntilMouseMoves_(True)
        self.preloadNext()

    def preloadNext(self):
        """Decode the photo after this one while the current one is on screen."""
        if not self.picker.count() or not self.picker.peek_forward_is_live():
            return
        path = self.picker.peek()
        if path is None:
            return
        if self._preloaded is not None and self._preloaded[0] == path:
            return
        self._queue.put(("preload", self._displayToken, path, self.slideshow.maxPixelSize()))

    # -- background decoding ---------------------------------------------
    def _workerLoop(self):
        while True:
            pool = NSAutoreleasePool.alloc().init()
            try:
                job = self._queue.get()
                if job is None:
                    return
                kind, token, path, max_pixels = job
                if kind == "display" and token != self._displayToken:
                    continue          # superseded by a newer request
                try:
                    image, when = pf_image.load_photo(path, max_pixels)
                except Exception:
                    log(u"Could not read %s\n%s" % (path, traceback.format_exc()))
                    image, when = None, None
                with self._lock:
                    self._results.append((kind, token, path, image, when))
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
                    b"drainResults:", None, False)
            finally:
                del pool

    def drainResults_(self, _ignored):
        with self._lock:
            results = self._results
            self._results = []

        for kind, token, path, image, when in results:
            if image is None:
                folder = self.cfg["folder"]
                library_there = bool(folder) and os.path.isdir(folder)
                if library_there:
                    # A genuinely broken file: forget it and move on.
                    log(u"Skipping unreadable file: %s" % path)
                    self.picker.drop(path)
                else:
                    # The whole folder has gone - an unplugged drive, most likely.
                    # Keep the index; the show recovers on its own when it returns.
                    log(u"Photo folder unavailable while loading %s" % path)

                if kind == "display" and token == self._displayToken:
                    self._failStreak += 1
                    if library_there and self._failStreak < 12 and self.picker.count():
                        self.advance_(1)
                    elif self.showing and not library_there:
                        self.slideshow.view.setStatus_(
                            u"Waiting for the photo folder…\n\n%s\n\n"
                            u"The frame carries on by itself once it is back." % folder)
                    elif self.showing:
                        self.slideshow.view.setStatus_(
                            u"These photos could not be opened.\nPress Esc to check the folder.")
                continue

            if kind == "preload":
                self._preloaded = (path, image, when)
            elif token == self._displayToken:
                self.displayPath_image_date_(path, image, when)

    # -- schedule ---------------------------------------------------------
    def scheduleTick_(self, timer):
        self.evaluateSchedule()

    def evaluateSchedule(self):
        cfg = self.cfg
        want_on = within_schedule(cfg)

        if want_on:
            if not self.showing:
                self.startShow()
            elif self.picker.count() and not self.currentPath and not self._scanning:
                self.advance_(1)
            return

        if self.showing:
            self.stopShow()
            self._sleepDeferUntil = 0.0

        if not cfg["sleep_when_off"]:
            return
        if self.settings is not None and self.settings.isVisible():
            return                                   # someone is using the Mac
        if time.time() < self._sleepDeferUntil:
            return
        self._sleepDeferUntil = time.time() + max(60.0, cfg["sleep_grace_minutes"] * 60.0)
        log(u"Outside the scheduled hours - sleeping the Mac.")
        ok, message = pf_system.sleep_now()
        if not ok:
            log(u"pmset sleepnow failed: %s" % message)

    def systemDidWake_(self, notification):
        log(u"The Mac woke up.")
        if self.slideshow is not None:
            self.slideshow.syncToScreen()
        # Give a person who woke it deliberately time to use it before we sleep again.
        if not within_schedule(self.cfg):
            self._sleepDeferUntil = time.time() + max(
                60.0, self.cfg["sleep_grace_minutes"] * 60.0)
        self.evaluateSchedule()

    def screensChanged_(self, notification):
        if self.slideshow is not None:
            self.slideshow.syncToScreen()

    # -- input ------------------------------------------------------------
    def handleKeyEvent_(self, event):
        code = event.keyCode()
        chars = (event.charactersIgnoringModifiers() or u"").lower()

        if code == KEY_ESCAPE or chars == u",":
            self.openSettings()
            return True
        if code == KEY_RIGHT or chars == u"n":
            self.advance_(1)
            self.restartAdvanceTimer()
            return True
        if code == KEY_LEFT or chars == u"p":
            self.advance_(-1)
            self.restartAdvanceTimer()
            return True
        if code == KEY_SPACE:
            self.togglePause()
            return True
        if chars == u"d":
            self.cfg["show_date"] = not self.cfg["show_date"]
            pf_config.save(self.cfg)
            self.slideshow.view.setCaption_(self.captionText())
            return True
        if chars == u"h" or chars == u"?":
            self.slideshow.view.setHint_(HINT_TEXT)
            if self.hintTimer is not None:
                self.hintTimer.invalidate()
            self.hintTimer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                pf_slideshow.HINT_SECONDS, self, b"hideHint:", None, False)
            return True
        return False

    def togglePause(self):
        self.paused = not self.paused
        if self.paused:
            self.stopAdvanceTimer()
            self.slideshow.view.setHint_(u"Paused - press Space to carry on")
        else:
            self.slideshow.view.setHint_(u"")
            self.restartAdvanceTimer()

    def slideshowClicked_(self, event):
        NSCursor.unhide()

    def menuNext_(self, sender):
        self.advance_(1)
        self.restartAdvanceTimer()

    def menuPrevious_(self, sender):
        self.advance_(-1)
        self.restartAdvanceTimer()

    def menuPause_(self, sender):
        self.togglePause()

    def menuRescan_(self, sender):
        self.startScanForced_(True)


def _thousands(number):
    return u"{:,}".format(int(number))


def main():
    app = NSApplication.sharedApplication()
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    # Keep a reference alive for the life of the process.
    globals()["_delegate"] = delegate
    app.run()


if __name__ == "__main__":
    main()
