# -*- coding: utf-8 -*-
"""The full-screen slideshow window.

Everything on screen is a CALayer, so the cross-fade is done by the GPU
instead of by redrawing two full-screen bitmaps in Quartz - which matters a
lot on 2009 hardware.
"""

from __future__ import print_function

from AppKit import (
    NSApp, NSBackingStoreBuffered, NSColor, NSCursor, NSFont, NSScreen, NSView,
    NSWindow, NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
)
from Foundation import NSMakeRect, NSMakeSize, NSObject

import Quartz

try:  # PyObjC 4+ wants its own super() inside Objective-C subclasses
    from objc import super       # noqa: A004
except ImportError:              # the PyObjC bundled with 10.13 has no objc.super
    pass

def _ca_class(name):
    """Core Animation class, however this PyObjC chooses to expose it."""
    found = getattr(Quartz, name, None)
    if found is None:
        import objc
        found = objc.lookUpClass(name)   # AppKit has already loaded QuartzCore
    return found


CALayer = _ca_class("CALayer")
CAGradientLayer = _ca_class("CAGradientLayer")
CATextLayer = _ca_class("CATextLayer")
CATransition = _ca_class("CATransition")
CATransaction = _ca_class("CATransaction")

kGravityAspect = getattr(Quartz, "kCAGravityResizeAspect", "resizeAspect")
kFilterTrilinear = getattr(Quartz, "kCAFilterTrilinear", "trilinear")
kFilterLinear = getattr(Quartz, "kCAFilterLinear", "linear")
kTransitionFade = getattr(Quartz, "kCATransitionFade", "fade")
kAlignRight = getattr(Quartz, "kCAAlignmentRight", "right")
kAlignCenter = getattr(Quartz, "kCAAlignmentCenter", "center")
kAlignLeft = getattr(Quartz, "kCAAlignmentLeft", "left")

# Borderless window that still sits above the menu bar and the Dock.
STYLE_BORDERLESS = 0
LEVEL_SLIDESHOW = 25          # NSStatusWindowLevel: over the menu bar
LEVEL_NORMAL = 0

CAPTION_MARGIN = 28.0
HINT_SECONDS = 9.0


def _cgcolor(r, g, b, a):
    return Quartz.CGColorCreateGenericRGB(r, g, b, a)


def _pick_font_name():
    for name in (u"HelveticaNeue-Medium", u"HelveticaNeue", u"Helvetica-Bold", u"Helvetica"):
        if NSFont.fontWithName_size_(name, 12.0) is not None:
            return name
    return u"Helvetica"


class SlideshowWindow(NSWindow):
    """Borderless, black, always-on-top, and able to take the keyboard."""

    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return True


class SlideshowView(NSView):
    """Hosts the photo layer, the date caption, and transient messages."""

    def initWithFrame_(self, frame):
        self = super(SlideshowView, self).initWithFrame_(frame)
        if self is None:
            return None

        self.controller = None
        self.fontName = _pick_font_name()
        self.captionSize = 22.0
        self.fadeSeconds = 1.0

        self.setWantsLayer_(True)
        root = self.layer()
        root.setBackgroundColor_(_cgcolor(0.0, 0.0, 0.0, 1.0))

        self.imageLayer = CALayer.layer()
        self.imageLayer.setContentsGravity_(kGravityAspect)
        self.imageLayer.setMinificationFilter_(kFilterTrilinear)
        self.imageLayer.setMagnificationFilter_(kFilterLinear)
        self.imageLayer.setBackgroundColor_(_cgcolor(0.0, 0.0, 0.0, 1.0))
        self.imageLayer.setZPosition_(0.0)
        root.addSublayer_(self.imageLayer)

        # A soft dark fade along the bottom edge. Without it a date landing on
        # sky, sand or snow is barely readable from across a room.
        self._captionText = u""
        self._hintText = u""
        self.scrimLayer = CAGradientLayer.layer()
        self.scrimLayer.setColors_([_cgcolor(0.0, 0.0, 0.0, 0.0),
                                    _cgcolor(0.0, 0.0, 0.0, 0.62)])
        self.scrimLayer.setLocations_([0.0, 1.0])
        self.scrimLayer.setStartPoint_(Quartz.CGPointMake(0.5, 1.0))
        self.scrimLayer.setEndPoint_(Quartz.CGPointMake(0.5, 0.0))
        self.scrimLayer.setZPosition_(5.0)
        self.scrimLayer.setOpacity_(0.0)
        root.addSublayer_(self.scrimLayer)

        self.captionLayer = self._makeTextLayer_(kAlignRight)
        self.captionLayer.setZPosition_(10.0)
        root.addSublayer_(self.captionLayer)

        self.statusLayer = self._makeTextLayer_(kAlignCenter)
        self.statusLayer.setZPosition_(20.0)
        self.statusLayer.setOpacity_(0.0)
        root.addSublayer_(self.statusLayer)

        self.hintLayer = self._makeTextLayer_(kAlignLeft)
        self.hintLayer.setZPosition_(20.0)
        self.hintLayer.setOpacity_(0.0)
        root.addSublayer_(self.hintLayer)

        self.layoutLayers()
        return self

    def _makeTextLayer_(self, alignment):
        layer = CATextLayer.layer()
        layer.setAlignmentMode_(alignment)
        layer.setForegroundColor_(_cgcolor(1.0, 1.0, 1.0, 0.92))
        layer.setFont_(self.fontName)
        layer.setFontSize_(self.captionSize)
        layer.setShadowColor_(_cgcolor(0.0, 0.0, 0.0, 1.0))
        layer.setShadowOpacity_(0.85)
        layer.setShadowRadius_(5.0)
        layer.setShadowOffset_(NSMakeSize(0.0, -1.0))
        layer.setTruncationMode_("end")
        layer.setString_(u"")
        return layer

    # -- geometry --------------------------------------------------------
    def isFlipped(self):
        return False

    def isOpaque(self):
        return True

    def acceptsFirstResponder(self):
        return True

    def setFrameSize_(self, size):
        super(SlideshowView, self).setFrameSize_(size)
        self.layoutLayers()

    def layoutLayers(self):
        bounds = self.bounds()
        width = bounds.size.width
        height = bounds.size.height
        scale = 1.0
        window = self.window()
        if window is not None:
            scale = window.backingScaleFactor() or 1.0

        CATransaction.begin()
        CATransaction.setDisableActions_(True)

        self.imageLayer.setFrame_(NSMakeRect(0, 0, width, height))
        self.imageLayer.setContentsScale_(scale)

        self.scrimLayer.setFrame_(NSMakeRect(
            0, 0, width, max(110.0, self.captionSize * 3.4)))

        caption_h = self.captionSize * 1.7
        self.captionLayer.setContentsScale_(scale)
        self.captionLayer.setFontSize_(self.captionSize)
        self.captionLayer.setFrame_(NSMakeRect(
            CAPTION_MARGIN, CAPTION_MARGIN,
            max(10.0, width - 2 * CAPTION_MARGIN), caption_h))

        status_size = max(18.0, min(40.0, height * 0.030))
        self.statusLayer.setContentsScale_(scale)
        self.statusLayer.setFontSize_(status_size)
        self.statusLayer.setFrame_(NSMakeRect(
            width * 0.1, (height - status_size * 4.0) / 2.0,
            width * 0.8, status_size * 4.0))

        hint_size = max(13.0, min(20.0, height * 0.016))
        self.hintLayer.setContentsScale_(scale)
        self.hintLayer.setFontSize_(hint_size)
        self.hintLayer.setFrame_(NSMakeRect(
            CAPTION_MARGIN, CAPTION_MARGIN,
            max(10.0, width - 2 * CAPTION_MARGIN), hint_size * 1.8))

        CATransaction.commit()

    # -- content ---------------------------------------------------------
    def setCaptionSize_(self, size):
        self.captionSize = float(size)
        self.layoutLayers()

    def setFadeSeconds_(self, seconds):
        self.fadeSeconds = max(0.0, float(seconds))

    def _fadeLayer_(self, layer):
        if self.fadeSeconds <= 0.01:
            return
        transition = CATransition.animation()
        transition.setType_(kTransitionFade)
        transition.setDuration_(self.fadeSeconds)
        layer.addAnimation_forKey_(transition, "contents")

    def showImage_caption_(self, image, caption):
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        self._fadeLayer_(self.imageLayer)
        self.imageLayer.setContents_(image)
        self._fadeLayer_(self.captionLayer)
        self.captionLayer.setString_(caption or u"")
        self._captionText = caption or u""
        CATransaction.commit()
        self.refreshScrim()

    def setCaption_(self, caption):
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        self.captionLayer.setString_(caption or u"")
        self._captionText = caption or u""
        CATransaction.commit()
        self.refreshScrim()

    def refreshScrim(self):
        """The bottom fade is only there when there is text sitting on it."""
        wanted = 1.0 if (self._captionText or self._hintText) else 0.0
        CATransaction.begin()
        CATransaction.setAnimationDuration_(max(0.35, self.fadeSeconds))
        self.scrimLayer.setOpacity_(wanted)
        CATransaction.commit()

    def setStatus_(self, text):
        """Big centred message. Pass an empty string to clear it."""
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        self.statusLayer.setString_(text or u"")
        self.statusLayer.setOpacity_(1.0 if text else 0.0)
        CATransaction.commit()

    def setHint_(self, text):
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        self.hintLayer.setString_(text or u"")
        CATransaction.commit()
        self._hintText = text or u""
        self.hintLayer.setOpacity_(0.8 if text else 0.0)
        self.refreshScrim()

    def fadeHintOut(self):
        self._hintText = u""
        CATransaction.begin()
        CATransaction.setAnimationDuration_(1.2)
        self.hintLayer.setOpacity_(0.0)
        if not self._captionText:
            self.scrimLayer.setOpacity_(0.0)
        CATransaction.commit()

    # -- input -----------------------------------------------------------
    def keyDown_(self, event):
        if self.controller is not None and self.controller.handleKeyEvent_(event):
            return
        super(SlideshowView, self).keyDown_(event)

    def mouseDown_(self, event):
        if self.controller is not None:
            self.controller.slideshowClicked_(event)


class SlideshowController(NSObject):
    """Owns the window and gives the app delegate a small, plain API."""

    def initWithDelegate_(self, delegate):
        self = super(SlideshowController, self).init()
        if self is None:
            return None
        self.delegate = delegate
        self.window = None
        self.view = None
        self.elevated = True
        self._buildWindow()
        return self

    def _buildWindow(self):
        screen = NSScreen.mainScreen() or (NSScreen.screens() or [None])[0]
        frame = screen.frame() if screen is not None else NSMakeRect(0, 0, 1440, 900)

        window = SlideshowWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, STYLE_BORDERLESS, NSBackingStoreBuffered, False)
        window.setBackgroundColor_(NSColor.blackColor())
        window.setOpaque_(True)
        window.setHasShadow_(False)
        window.setLevel_(LEVEL_SLIDESHOW)
        window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary)
        window.setAcceptsMouseMovedEvents_(True)
        window.setReleasedWhenClosed_(False)

        view = SlideshowView.alloc().initWithFrame_(
            NSMakeRect(0, 0, frame.size.width, frame.size.height))
        view.controller = self.delegate
        window.setContentView_(view)
        window.makeFirstResponder_(view)

        self.window = window
        self.view = view

    # -- window management ----------------------------------------------
    def maxPixelSize(self):
        """Longest screen edge in real pixels - the decode target for photos."""
        frame = self.window.frame()
        scale = self.window.backingScaleFactor() or 1.0
        return int(max(frame.size.width, frame.size.height) * scale)

    def show(self):
        self.window.makeKeyAndOrderFront_(None)
        NSApp().activateIgnoringOtherApps_(True)
        self.elevate_(True)
        NSCursor.setHiddenUntilMouseMoves_(True)

    def hide(self):
        self.window.orderOut_(None)

    def isVisible(self):
        return bool(self.window.isVisible())

    def elevate_(self, elevated):
        """Drop out of the way while Settings or an open panel is up."""
        self.elevated = bool(elevated)
        self.window.setLevel_(LEVEL_SLIDESHOW if elevated else LEVEL_NORMAL)
        if elevated and self.window.isVisible():
            self.window.orderFrontRegardless()
            NSCursor.setHiddenUntilMouseMoves_(True)

    def syncToScreen(self):
        """Re-fit the window after a resolution or display change."""
        screen = NSScreen.mainScreen() or (NSScreen.screens() or [None])[0]
        if screen is None:
            return
        frame = screen.frame()
        self.window.setFrame_display_(frame, True)
        self.view.setFrameSize_(frame.size)
        self.view.layoutLayers()
