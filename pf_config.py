# -*- coding: utf-8 -*-
"""Settings storage for Photo Frame.

Runs on Python 2.7 (macOS 10.13 system Python) and Python 3.
Settings live in ~/Library/Application Support/PhotoFrame/config.json
so they are easy to inspect or hand-edit on the frame machine.
"""

from __future__ import print_function

import errno
import json
import os

APP_NAME = "PhotoFrame"

DEFAULTS = {
    # Library
    "folder": "",

    # Playback
    "seconds_per_photo": 15.0,
    "fade_seconds": 1.0,
    "random_mode": "true_random",     # "true_random" | "shuffle"
    "no_repeat_window": 200,          # true_random: don't repeat within N photos

    # Caption
    "show_date": True,
    "date_format": "long",            # long | medium | month_year | iso | year
    "caption_size": 22,

    # Schedule
    "schedule_enabled": False,
    "start_time": "08:00",
    "end_time": "22:00",
    "sleep_when_off": True,
    "sleep_grace_minutes": 5,         # after a manual wake outside hours

    # Housekeeping
    "rescan_hours": 12.0,
    "manage_screen_saver": True,      # keep the screen saver off the slideshow
}

_TIME_KEYS = ("start_time", "end_time")


def support_dir():
    path = os.path.expanduser("~/Library/Application Support/" + APP_NAME)
    try:
        os.makedirs(path)
    except OSError as exc:
        if exc.errno != errno.EEXIST:
            raise
    return path


def config_path():
    return os.path.join(support_dir(), "config.json")


def index_path():
    return os.path.join(support_dir(), "index.json")


def log_path():
    return os.path.join(support_dir(), "photoframe.log")


def parse_hhmm(value, fallback=(0, 0)):
    """'08:30' -> (8, 30). Tolerant of junk; returns fallback on failure."""
    try:
        text = str(value).strip()
        if ":" in text:
            hh, mm = text.split(":", 1)
        else:  # allow "0830" / "8"
            text = text.zfill(4) if len(text) > 2 else text + "00"
            hh, mm = text[:-2], text[-2:]
        hh = max(0, min(23, int(hh)))
        mm = max(0, min(59, int(mm)))
        return (hh, mm)
    except Exception:
        return fallback


def format_hhmm(hh, mm):
    return "%02d:%02d" % (hh, mm)


def _clamp(value, low, high, fallback):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    if value != value:  # NaN
        return fallback
    return max(low, min(high, value))


def sanitize(cfg):
    """Force every value into a sane range so a hand-edited file can't break the app."""
    out = dict(DEFAULTS)
    out.update({k: v for k, v in cfg.items() if k in DEFAULTS})

    out["folder"] = out["folder"] if isinstance(out["folder"], str) or _is_text(out["folder"]) else ""
    out["seconds_per_photo"] = _clamp(out["seconds_per_photo"], 1.0, 3600.0, 15.0)
    out["fade_seconds"] = _clamp(out["fade_seconds"], 0.0, 10.0, 1.0)
    out["caption_size"] = int(_clamp(out["caption_size"], 10, 96, 22))
    out["no_repeat_window"] = int(_clamp(out["no_repeat_window"], 0, 100000, 200))
    out["sleep_grace_minutes"] = int(_clamp(out["sleep_grace_minutes"], 0, 240, 5))
    out["rescan_hours"] = _clamp(out["rescan_hours"], 0.0, 720.0, 12.0)

    if out["random_mode"] not in ("true_random", "shuffle"):
        out["random_mode"] = "true_random"
    if out["date_format"] not in ("long", "medium", "month_year", "iso", "year"):
        out["date_format"] = "long"

    for key in _TIME_KEYS:
        hh, mm = parse_hhmm(out[key], parse_hhmm(DEFAULTS[key]))
        out[key] = format_hhmm(hh, mm)

    for key in ("show_date", "schedule_enabled", "sleep_when_off", "manage_screen_saver"):
        out[key] = bool(out[key])

    return out


def _is_text(value):
    try:
        return isinstance(value, unicode)  # noqa: F821  (Python 2)
    except NameError:
        return False


def load():
    try:
        with open(config_path(), "rb") as handle:
            raw = json.loads(handle.read().decode("utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except Exception:
        raw = {}
    return sanitize(raw)


def save(cfg):
    cfg = sanitize(cfg)
    path = config_path()
    tmp = path + ".tmp"
    data = json.dumps(cfg, indent=2, sort_keys=True, ensure_ascii=False)
    if not isinstance(data, bytes):
        data = data.encode("utf-8")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.write(b"\n")
    os.rename(tmp, path)
    return cfg
