# -*- coding: utf-8 -*-
"""Photo discovery, on-disk index cache, and the random picker.

Designed for libraries in the 10,000+ range: the folder walk happens on a
background thread, the resulting path list is cached to JSON so restarts are
instant, and picking is O(1).
"""

from __future__ import print_function

import json
import os
import random
import time

import pf_config

IMAGE_EXTS = frozenset([
    ".jpg", ".jpeg", ".jpe", ".jfif",
    ".png", ".gif", ".bmp", ".tif", ".tiff",
    ".heic", ".heif",
    ".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".raf", ".rw2", ".pef", ".srw",
])

# Directories that only ever hold derivatives, never originals worth showing.
SKIP_DIR_NAMES = frozenset([
    "thumbnails", "previews", "resources", "database", "private",
    ".photoslibrary_derivatives", "caches", "cache",
])

# Photo/iPhoto libraries are packages: descend only into the originals.
LIBRARY_SUFFIXES = (".photoslibrary", ".aplibrary", ".migratedphotolibrary", ".photolibrary")
LIBRARY_ORIGINAL_DIRS = frozenset(["originals", "masters"])

MIN_FILE_BYTES = 1024  # skip zero-byte / placeholder files


def _to_text(path):
    if isinstance(path, bytes):
        return path.decode("utf-8", "replace")
    return path


def scan(folder, should_stop=None, progress=None):
    """Walk *folder* and return a sorted list of image paths (unicode).

    should_stop: optional callable -> True to abort early (returns partial list).
    progress:    optional callable(count) invoked every few hundred finds.
    """
    folder = _to_text(os.path.expanduser(folder))
    found = []
    if not folder or not os.path.isdir(folder):
        return found

    last_report = 0
    for dirpath, dirnames, filenames in os.walk(folder):
        if should_stop is not None and should_stop():
            break

        in_library = any(part.lower().endswith(LIBRARY_SUFFIXES)
                         for part in dirpath.split(os.sep))

        keep = []
        for name in dirnames:
            lower = name.lower()
            if name.startswith("."):
                continue
            if lower.endswith(LIBRARY_SUFFIXES):
                keep.append(name)          # descend one level into the package
                continue
            if in_library and lower in SKIP_DIR_NAMES and lower not in LIBRARY_ORIGINAL_DIRS:
                continue
            keep.append(name)
        dirnames[:] = keep

        for name in filenames:
            if name.startswith("."):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in IMAGE_EXTS:
                continue
            full = os.path.join(dirpath, name)
            try:
                if os.path.getsize(full) < MIN_FILE_BYTES:
                    continue
            except OSError:
                continue
            found.append(_to_text(full))

        if progress is not None and len(found) - last_report >= 500:
            last_report = len(found)
            progress(len(found))

    found.sort()
    if progress is not None:
        progress(len(found))
    return found


def load_index(folder):
    """Return (paths, scanned_at) from the cache, or ([], 0) if it doesn't match."""
    try:
        with open(pf_config.index_path(), "rb") as handle:
            data = json.loads(handle.read().decode("utf-8"))
        if _to_text(data.get("folder", "")) != _to_text(os.path.expanduser(folder or "")):
            return [], 0.0
        paths = [_to_text(p) for p in data.get("paths", [])]
        return paths, float(data.get("scanned_at", 0.0))
    except Exception:
        return [], 0.0


def save_index(folder, paths):
    payload = {
        "folder": _to_text(os.path.expanduser(folder or "")),
        "scanned_at": time.time(),
        "count": len(paths),
        "paths": paths,
    }
    path = pf_config.index_path()
    tmp = path + ".tmp"
    data = json.dumps(payload, ensure_ascii=False)
    if not isinstance(data, bytes):
        data = data.encode("utf-8")
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.rename(tmp, path)
    except Exception:
        pass


class Picker(object):
    """Chooses the next photo.

    true_random: every photo is independently equally likely (drawn from
                 os.urandom via random.SystemRandom), with an optional window
                 that suppresses immediate repeats.
    shuffle:     a reshuffled deck - every photo shown once per pass.
    """

    def __init__(self, paths=None, mode="true_random", no_repeat_window=200):
        self._rng = random.SystemRandom()
        self.mode = mode
        self.no_repeat_window = no_repeat_window
        self._paths = []
        self._recent = []
        self._recent_set = set()
        self._deck = []
        self._peeked = None        # drawn early so it can be decoded in advance
        self.history = []          # what has actually been displayed
        self.history_pos = -1      # index into history when stepping backwards
        self.set_paths(paths or [])

    # -- library ---------------------------------------------------------
    def set_paths(self, paths):
        self._paths = list(paths)
        self._deck = []
        self._peeked = None
        known = set(self._paths)
        self._recent = [p for p in self._recent if p in known] if self._paths else []
        self._recent_set = set(self._recent)

    def set_mode(self, mode, no_repeat_window=None):
        if mode != self.mode:
            self.mode = mode
            self._deck = []
            self._peeked = None
        if no_repeat_window is not None:
            self.no_repeat_window = no_repeat_window
            self._trim_recent()

    def count(self):
        return len(self._paths)

    def drop(self, path):
        """Forget a path that turned out to be unreadable."""
        try:
            self._paths.remove(path)
        except ValueError:
            pass
        self._deck = [p for p in self._deck if p != path]
        if self._peeked == path:
            self._peeked = None

    # -- selection -------------------------------------------------------
    def _window(self):
        if self.no_repeat_window <= 0 or len(self._paths) < 2:
            return 0
        # Never suppress more than half the library, or we'd starve.
        return min(self.no_repeat_window, len(self._paths) // 2)

    def _trim_recent(self):
        limit = self._window()
        while len(self._recent) > limit:
            self._recent_set.discard(self._recent.pop(0))

    def _remember(self, path):
        self._recent.append(path)
        self._recent_set.add(path)
        self._trim_recent()

    def _pick_true_random(self):
        n = len(self._paths)
        window = self._window()
        if window:
            # Rejection sampling: cheap, and window <= n/2 bounds the retries.
            for _ in range(40):
                path = self._paths[self._rng.randrange(n)]
                if path not in self._recent_set:
                    return path
        return self._paths[self._rng.randrange(n)]

    def _pick_shuffle(self):
        if not self._deck:
            self._deck = list(self._paths)
            self._rng.shuffle(self._deck)
            # Avoid the seam where a new deck repeats the photo just shown.
            if len(self._deck) > 1 and self.history and self._deck[-1] == self.history[-1]:
                self._deck[0], self._deck[-1] = self._deck[-1], self._deck[0]
        return self._deck.pop()

    def _draw(self):
        if not self._paths:
            return None
        path = self._pick_shuffle() if self.mode == "shuffle" else self._pick_true_random()
        self._remember(path)
        return path

    def peek(self):
        """The photo next() will return, chosen now so it can be decoded early."""
        if self._peeked is None:
            self._peeked = self._draw()
        return self._peeked

    def next(self):
        """Advance forwards. Returns a path, or None if the library is empty."""
        # Stepping forward after going back replays the recorded history.
        if self.history_pos >= 0 and self.history_pos < len(self.history) - 1:
            self.history_pos += 1
            return self.history[self.history_pos]

        if not self._paths:
            return None
        path, self._peeked = self._peeked, None
        if path is None:
            path = self._draw()
        if path is None:
            return None
        self.history.append(path)
        if len(self.history) > 500:
            del self.history[:100]
        self.history_pos = len(self.history) - 1
        return path

    def previous(self):
        """Step back through what was actually shown. None if there's no history."""
        if self.history_pos <= 0:
            return None
        self.history_pos -= 1
        return self.history[self.history_pos]

    def peek_forward_is_live(self):
        """True when next() will draw a fresh photo rather than replay history."""
        return not (0 <= self.history_pos < len(self.history) - 1)
