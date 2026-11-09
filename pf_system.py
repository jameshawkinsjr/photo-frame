# -*- coding: utf-8 -*-
"""Talking to macOS: sleep, scheduled wake, keep-awake, login item.

Only the wake schedule needs an administrator password (it writes to the
power management daemon). Everything else runs as the logged-in user.
"""

from __future__ import print_function

import os
import subprocess
import sys

PMSET = "/usr/bin/pmset"
CAFFEINATE = "/usr/bin/caffeinate"
OSASCRIPT = "/usr/bin/osascript"
DEFAULTS_CMD = "/usr/bin/defaults"

WAKE_DAYS = "MTWRFSU"
WAKE_LEAD_MINUTES = 2  # wake slightly before the slideshow is due to start


def run(args, timeout_hint=None):
    """Run a command, returning (rc, stdout, stderr) as text. Never raises."""
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = proc.communicate()
        return proc.returncode, _text(out), _text(err)
    except Exception as exc:
        return 1, u"", u"%s" % exc


def _text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or u""


def _as_applescript_string(text):
    return text.replace(u"\\", u"\\\\").replace(u'"', u'\\"')


def admin_shell(command, prompt=u"Photo Frame needs your password to change the Mac's wake schedule."):
    """Run *command* as root via the standard macOS password dialog."""
    script = u'do shell script "%s" with administrator privileges with prompt "%s"' % (
        _as_applescript_string(command), _as_applescript_string(prompt))
    rc, out, err = run([OSASCRIPT, "-e", script])
    if rc == 0:
        return True, out.strip()
    if u"-128" in err or u"User canceled" in err or u"User cancelled" in err:
        return False, u"Cancelled."
    return False, err.strip() or u"Command failed."


# -- power ---------------------------------------------------------------

def sleep_now():
    """Put the Mac to sleep. No password needed."""
    rc, out, err = run([PMSET, "sleepnow"])
    return rc == 0, (err or out).strip()


def wake_display():
    """Nudge the display awake without waking a sleeping machine."""
    try:
        subprocess.Popen([CAFFEINATE, "-u", "-t", "3"])
        return True
    except Exception:
        return False


def wake_time_for(start_hhmm):
    """Wake a couple of minutes before the start time, wrapping past midnight."""
    from pf_config import parse_hhmm, format_hhmm
    hh, mm = parse_hhmm(start_hhmm)
    total = (hh * 60 + mm - WAKE_LEAD_MINUTES) % (24 * 60)
    return format_hhmm(total // 60, total % 60)


def install_wake_schedule(start_hhmm):
    wake_at = wake_time_for(start_hhmm)
    command = u"%s repeat wakeorpoweron %s %s:00" % (PMSET, WAKE_DAYS, wake_at)
    ok, message = admin_shell(command)
    if ok:
        return True, u"The Mac will wake every day at %s." % wake_at
    return False, message


def remove_wake_schedule():
    ok, message = admin_shell(
        u"%s repeat cancel" % PMSET,
        u"Photo Frame needs your password to remove the Mac's wake schedule.")
    if ok:
        return True, u"Daily wake schedule removed."
    return False, message


def wake_schedule_summary():
    """One-line description of any repeating wake currently installed."""
    rc, out, err = run([PMSET, "-g", "sched"])
    if rc != 0:
        return u"Could not read the system schedule."
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("repeating"):
            continue
        if "wakepoweron" in stripped.lower() or "wakeorpoweron" in stripped.lower():
            return stripped
    if "Repeating power events" in out:
        tail = out.split("Repeating power events", 1)[1].strip().splitlines()
        if tail:
            return tail[0].strip()
    return u"No daily wake is currently scheduled."


class Caffeinator(object):
    """Holds the display and system awake for as long as the show is running."""

    def __init__(self):
        self._proc = None

    def start(self):
        if self._proc is not None and self._proc.poll() is None:
            return
        try:
            self._proc = subprocess.Popen([CAFFEINATE, "-d", "-i", "-s"])
        except Exception:
            self._proc = None

    def stop(self):
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait()
        except Exception:
            pass

    def is_running(self):
        return self._proc is not None and self._proc.poll() is None


# -- login item and screen saver -----------------------------------------

def app_bundle_path():
    """Path of the enclosing .app, or None when running as a loose script."""
    path = os.path.abspath(sys.argv[0] if sys.argv and sys.argv[0] else __file__)
    while path and path != "/":
        if path.endswith(".app"):
            return path
        path = os.path.dirname(path)
    return None


def login_item_name(app_path):
    return os.path.splitext(os.path.basename(app_path))[0]


def login_item_enabled(app_path):
    if not app_path:
        return False
    name = _as_applescript_string(login_item_name(app_path))
    script = (u'tell application "System Events" to get the name of every login item')
    rc, out, err = run([OSASCRIPT, "-e", script])
    if rc != 0:
        return False
    return name.lower() in [part.strip().lower() for part in out.split(",")]


def set_login_item(enabled, app_path):
    if not app_path:
        return False, u"Photo Frame must be installed as an app before it can open at login."
    name = _as_applescript_string(login_item_name(app_path))
    if enabled:
        script = (
            u'tell application "System Events"\n'
            u'  if not (exists login item "%s") then\n'
            u'    make login item at end with properties {path:"%s", hidden:false}\n'
            u'  end if\n'
            u'end tell' % (name, _as_applescript_string(app_path)))
    else:
        script = (
            u'tell application "System Events"\n'
            u'  if exists login item "%s" then delete login item "%s"\n'
            u'end tell' % (name, name))
    rc, out, err = run([OSASCRIPT, "-e", script])
    if rc == 0:
        return True, u""
    return False, err.strip() or u"Could not change the login items."


def screen_saver_disabled():
    rc, out, err = run([DEFAULTS_CMD, "-currentHost", "read",
                        "com.apple.screensaver", "idleTime"])
    return rc == 0 and out.strip() == "0"


def set_screen_saver_disabled(disabled):
    """Stop the screen saver sliding in over the slideshow, or put it back.

    This is a per-user preference, so turning it back off restores whatever
    the Mac's own default is rather than guessing at a previous value.
    """
    if disabled:
        rc, out, err = run([DEFAULTS_CMD, "-currentHost", "write",
                            "com.apple.screensaver", "idleTime", "-int", "0"])
    else:
        rc, out, err = run([DEFAULTS_CMD, "-currentHost", "delete",
                            "com.apple.screensaver", "idleTime"])
        rc = 0   # deleting a key that was never set is not a failure
    return rc == 0
