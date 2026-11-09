# -*- coding: utf-8 -*-
"""Decoding photos and reading their dates, via ImageIO.

Photos are decoded straight to screen size with CGImageSourceCreateThumbnailAtIndex
rather than loaded at full resolution: a 20 megapixel JPEG becomes a ~2 megapixel
bitmap, which is what keeps this comfortable on a 2009 iMac.
"""

from __future__ import print_function

import datetime
import os

from Foundation import NSURL

import Quartz


def _const(name, literal):
    """ImageIO constant, falling back to its documented string value.

    The PyObjC that ships with 10.13 exposes slightly different symbol sets
    depending on the framework bindings available, and these constants are all
    plain CFStrings, so the literal is always a safe substitute.
    """
    return getattr(Quartz, name, literal)


kThumbFromImageAlways = _const("kCGImageSourceCreateThumbnailFromImageAlways",
                               "kCGImageSourceCreateThumbnailFromImageAlways")
kThumbMaxPixelSize = _const("kCGImageSourceThumbnailMaxPixelSize",
                            "kCGImageSourceThumbnailMaxPixelSize")
kThumbWithTransform = _const("kCGImageSourceCreateThumbnailWithTransform",
                             "kCGImageSourceCreateThumbnailWithTransform")
kShouldCache = _const("kCGImageSourceShouldCache", "kCGImageSourceShouldCache")

kExifDict = _const("kCGImagePropertyExifDictionary", "{Exif}")
kExifOriginal = _const("kCGImagePropertyExifDateTimeOriginal", "DateTimeOriginal")
kExifDigitized = _const("kCGImagePropertyExifDateTimeDigitized", "DateTimeDigitized")
kTiffDict = _const("kCGImagePropertyTIFFDictionary", "{TIFF}")
kTiffDateTime = _const("kCGImagePropertyTIFFDateTime", "DateTime")
kIptcDict = _const("kCGImagePropertyIPTCDictionary", "{IPTC}")

MONTHS = (u"January", u"February", u"March", u"April", u"May", u"June",
          u"July", u"August", u"September", u"October", u"November", u"December")
MONTHS_SHORT = (u"Jan", u"Feb", u"Mar", u"Apr", u"May", u"Jun",
                u"Jul", u"Aug", u"Sep", u"Oct", u"Nov", u"Dec")

_MIN_YEAR = 1826  # the oldest surviving photograph
_MAX_YEAR = datetime.date.today().year + 1


def _make_source(path):
    url = NSURL.fileURLWithPath_(path)
    if url is None:
        return None
    return Quartz.CGImageSourceCreateWithURL(url, None)


def _parse_exif_datetime(text):
    """EXIF stamps look like '2009:08:12 14:23:01'; be forgiving about the rest."""
    if not text:
        return None
    text = u"%s" % text
    text = text.strip().replace(u"/", u":").replace(u"-", u":")
    if u"." in text:
        text = text.split(u".", 1)[0]
    if u"+" in text:
        text = text.split(u"+", 1)[0].strip()
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y:%m:%d %H:%M", "%Y:%m:%d"):
        try:
            parsed = datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
        if _MIN_YEAR <= parsed.year <= _MAX_YEAR:
            return parsed
    return None


def _file_datetime(path):
    """Best guess from the filesystem: the earlier of created and modified."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    stamps = [stat.st_mtime]
    birth = getattr(stat, "st_birthtime", None)
    if birth:
        stamps.append(birth)
    try:
        best = datetime.datetime.fromtimestamp(min(stamps))
    except (ValueError, OverflowError, OSError):
        return None
    if _MIN_YEAR <= best.year <= _MAX_YEAR:
        return best
    return None


def date_from_source(source, path):
    """EXIF capture date if present, otherwise the file's own date."""
    props = None
    if source is not None:
        try:
            props = Quartz.CGImageSourceCopyPropertiesAtIndex(source, 0, None)
        except Exception:
            props = None

    if props:
        exif = props.get(kExifDict)
        if exif:
            for key in (kExifOriginal, kExifDigitized):
                found = _parse_exif_datetime(exif.get(key))
                if found:
                    return found
        tiff = props.get(kTiffDict)
        if tiff:
            found = _parse_exif_datetime(tiff.get(kTiffDateTime))
            if found:
                return found
        iptc = props.get(kIptcDict)
        if iptc:
            found = _parse_exif_datetime(iptc.get("DateCreated"))
            if found:
                return found

    return _file_datetime(path)


def photo_date(path):
    """Convenience wrapper when only the date is wanted."""
    source = _make_source(path)
    return date_from_source(source, path)


def load_photo(path, max_pixel_size):
    """Return (CGImage, datetime or None). CGImage is None if unreadable."""
    source = _make_source(path)
    if source is None:
        return None, None

    when = date_from_source(source, path)

    options = {
        kThumbFromImageAlways: True,
        kThumbWithTransform: True,      # honour the EXIF orientation flag
        kThumbMaxPixelSize: int(max_pixel_size),
        kShouldCache: False,
    }
    try:
        image = Quartz.CGImageSourceCreateThumbnailAtIndex(source, 0, options)
    except Exception:
        image = None

    if image is None:
        # Some formats refuse the thumbnail path; fall back to a full decode.
        try:
            image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, {kShouldCache: False})
        except Exception:
            image = None

    return image, when


def image_size(image):
    if image is None:
        return (0, 0)
    return (Quartz.CGImageGetWidth(image), Quartz.CGImageGetHeight(image))


def format_date(when, style="long"):
    """Human caption for a photo date. Returns u'' when the date is unknown."""
    if when is None:
        return u""
    if style == "year":
        return u"%d" % when.year
    if style == "iso":
        return u"%04d-%02d-%02d" % (when.year, when.month, when.day)
    if style == "month_year":
        return u"%s %d" % (MONTHS[when.month - 1], when.year)
    if style == "medium":
        return u"%d %s %d" % (when.day, MONTHS_SHORT[when.month - 1], when.year)
    return u"%d %s %d" % (when.day, MONTHS[when.month - 1], when.year)
