# Copyright (C) 2020
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""On-screen recording indicator: a small draggable "pill" overlay.

The pill shows a microphone badge, a live level meter fed by the default
source while it is unmuted, and the active voice effect if any. The state is
carried by the badge color: gray (muted), red (live), amber (locked). It is
rendered antialiased with Pillow and, on X11 (or XWayland), the window is
given rounded edges with the X SHAPE extension.
"""

import array
import contextlib
import math
import os
import shutil
import subprocess
import threading
import tkinter as tk
from collections import deque
from collections.abc import Callable

from PIL import Image, ImageDraw, ImageFont, ImageTk
from pulsectl import Pulse

from .voice import SOURCE_NAME as VIRTUAL_MIC

# Palette (RGB)
BG = (22, 22, 26)
BORDER = (52, 52, 60)
BADGE_MUTED = (50, 50, 57)
FG_MUTED = (135, 135, 146)
BARS_MUTED = (68, 68, 77)
FG_LIVE = (242, 242, 246)
RED = (255, 59, 48)
AMBER = (255, 159, 10)

SUPERSAMPLE = 3  # Render 3x larger then downscale, for smooth edges
FRAME_MS = 33  # ~30 fps animation
POLL_MS = 100  # Mute state polling interval
BARS = 12  # Number of level meter bars
VISIBLE = 0.01  # Below this mix, live-only decorations are skipped


def _mix(a: tuple, b: tuple, t: float) -> tuple:
    """Linearly interpolate two RGB colors."""
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b, strict=True))


def _font(size: int) -> ImageFont.FreeTypeFont:
    """Return a bold sans font, falling back to Pillow's bundled font."""
    for name in ('DejaVuSans-Bold.ttf', 'Inter-Bold.ttf', 'Arial Bold.ttf'):
        with contextlib.suppress(OSError):
            return ImageFont.truetype(name, size)
    return ImageFont.load_default(size=size)


class LevelMeter:
    """Measure the default source level with a light ``parec`` stream.

    The stream only runs while recording, so the microphone is not kept
    open (and desktop "mic in use" indicators stay off) while muted.
    """

    RATE = 16000
    CHUNK = 320  # 20 ms of 16-bit mono samples

    def __init__(self) -> None:
        """Init the meter; the stream is started with :meth:`start`."""
        self.level = 0.0
        self.proc: subprocess.Popen | None = None
        self.available = shutil.which('parec') is not None

    def start(self) -> None:
        """Start measuring (no-op if already running or parec missing)."""
        if self.proc is not None or not self.available:
            return
        self.proc = subprocess.Popen(
            [
                'parec',
                '--raw',
                '--format=s16le',
                '--channels=1',
                f'--rate={self.RATE}',
                '--latency-msec=20',
                '--client-name=pulseToTalk',
                '--stream-name=level-meter',
            ],
            stdout=subprocess.PIPE,
            bufsize=0,
        )
        reader = threading.Thread(target=self._read, args=(self.proc,), daemon=True)
        reader.start()

    def _read(self, proc: subprocess.Popen) -> None:
        """Convert each chunk to a 0..1 level (-50 dBFS .. -10 dBFS)."""
        fd = proc.stdout.fileno()
        with contextlib.suppress(OSError):
            while data := os.read(fd, self.CHUNK * 2):
                samples = array.array('h', data[: len(data) // 2 * 2])
                if not samples:
                    continue
                rms = math.sqrt(sum(s * s for s in samples) / len(samples))
                db = 20 * math.log10(max(rms, 1) / 32768)
                self.level = min(max((db + 50) / 40, 0.0), 1.0)

    def stop(self) -> None:
        """Stop measuring."""
        if self.proc is not None:
            self.proc.terminate()
            self.proc = None
        self.level = 0.0


class RecordingIndicator(tk.Tk):
    """Hidden root window driving the overlay pill from the mute state."""

    def __init__(
        self,
        is_locked: Callable[[], bool] | None = None,
        label: str | None = None,
    ) -> None:
        """Create the overlay and its own pulseaudio connection.

        Args:
            is_locked: Returns True while recording is locked (Ctrl + key).
            label: Optional text shown after the meter, e.g. a voice effect.
        """
        super().__init__()

        # Remove root window to avoid two windows
        # See : https://stackoverflow.com/a/48289343/1079254
        self.withdraw()

        # Init pulse (do not support multi-thread !)
        self.pulse = Pulse(self.__class__.__name__)

        self.is_locked = is_locked or (lambda: False)
        self.meter = LevelMeter()
        self.live = False
        self.mix = 0.0  # 0 = muted look, 1 = live look (animated)
        self.phase = 0.0
        self.levels: deque[float] = deque([0.0] * BARS, maxlen=BARS)
        self.smoothed = 0.0

        self.overlay = Overlay(self, label.upper() if label else None)

    def start(self) -> None:
        """Start the polling and animation loops on tkinter's scheduler."""
        self._poll()
        self._frame()

    def stop(self) -> None:
        """Release resources (level meter stream)."""
        self.meter.stop()

    def _poll(self) -> None:
        """Refresh the mute state and start/stop the level meter."""
        live = not self.is_sources_muted()
        if live != self.live:
            self.live = live
            if live:
                self.meter.start()
            else:
                self.meter.stop()
        self.after(POLL_MS, self._poll)

    def _frame(self) -> None:
        """Advance the animation by one frame and redraw."""
        target = 1.0 if self.live else 0.0
        self.mix += (target - self.mix) * 0.25
        self.phase = (self.phase + 0.08) % (2 * math.pi) if self.live else 0.0
        # Fast attack, slow release for a lively but readable meter
        level = self.meter.level if self.live else 0.0
        rate = 0.6 if level > self.smoothed else 0.15
        self.smoothed += (level - self.smoothed) * rate
        self.levels.append(self.smoothed)

        self.overlay.render(
            mix=self.mix,
            phase=self.phase,
            levels=list(self.levels),
            accent=AMBER if self.live and self.is_locked() else RED,
        )
        self.after(FRAME_MS, self._frame)

    def is_sources_muted(self) -> bool:
        """Return False if at least one source is recording."""
        for source in self.pulse.source_list():
            # Exclude monitors input, and the voice changer's virtual mic
            # which stays open (it is gated by the real mic it is fed from)
            if source.name.endswith('.monitor') or source.name == VIRTUAL_MIC:
                continue
            # mute = 0 mean recording
            if source.mute == 0:
                return False
        # No source recording found, all are muted
        return True


class Overlay(tk.Toplevel):
    """Borderless always-on-top pill window.

    Drag it with the left mouse button; Ctrl + mouse wheel resizes it.
    """

    HEIGHT = 34
    ZOOM_STEP = 1.1
    # Below 0.8 the mic glyph and the label are no longer legible
    ZOOM_MIN, ZOOM_MAX = 0.8, 3.0

    def __init__(self, master: tk.Tk, text: str | None = None) -> None:
        """Build the overlay window, sized to fit the optional text."""
        super().__init__(master)

        self.overrideredirect(True)
        self.attributes('-topmost', True)
        with contextlib.suppress(tk.TclError):
            self.attributes('-alpha', 0.95)

        # HiDPI : base scale from the screen DPI (96 = 1x), times user zoom
        self.base_scale = max(1.0, self.winfo_fpixels('1i') / 96)
        self.zoom = 1.0
        self.text = text

        self.label = tk.Label(self, bd=0, bg='#16161a')
        self.label.pack()
        self._layout()
        x = int((self.winfo_screenwidth() - self.w) / 2)
        self.geometry(f'{self.w}x{self.h}+{x}+8')

        self.label.bind('<ButtonPress-1>', self.start_move)
        self.label.bind('<ButtonRelease-1>', self.stop_move)
        self.label.bind('<B1-Motion>', self.on_motion)
        # Ctrl + wheel : X11 reports the wheel as buttons 4 / 5 (Tk 8.6),
        # newer Tk versions as <MouseWheel>
        self.label.bind('<Control-Button-4>', lambda _e: self.zoom_by(1))
        self.label.bind('<Control-Button-5>', lambda _e: self.zoom_by(-1))
        self.label.bind(
            '<Control-MouseWheel>',
            lambda e: self.zoom_by(1 if e.delta > 0 else -1),
        )

        self.update_idletasks()
        self._round_corners()

    def _layout(self) -> None:
        """Compute every dimension from the current scale."""
        u = self.scale = self.base_scale * self.zoom
        self.font = _font(round(10 * u * SUPERSAMPLE))
        self.h = round(self.HEIGHT * u)
        self.badge_x = 9 * u + 11 * u  # Badge center
        self.bars_x = self.badge_x + 11 * u + 10 * u
        bars_end = self.bars_x + BARS * 5 * u - 2 * u
        if self.text:
            self.text_x = bars_end + 10 * u
            text_w = self.font.getlength(self.text) / SUPERSAMPLE
            self.w = round(self.text_x + text_w + 14 * u)
        else:
            self.w = round(bars_end + 14 * u)
        self.photo = ImageTk.PhotoImage(Image.new('RGB', (self.w, self.h), BG))
        self.label.configure(image=self.photo)

    def zoom_by(self, steps: int) -> None:
        """Grow (steps > 0) or shrink (steps < 0) the pill around its center."""
        zoom = self.zoom * self.ZOOM_STEP**steps
        zoom = min(max(zoom, self.ZOOM_MIN), self.ZOOM_MAX)
        if zoom == self.zoom:
            return
        cx = self.winfo_x() + self.w / 2
        cy = self.winfo_y() + self.h / 2
        self.zoom = zoom
        self._layout()
        x, y = round(cx - self.w / 2), round(cy - self.h / 2)
        self.geometry(f'{self.w}x{self.h}+{x}+{y}')
        self.update_idletasks()
        self._round_corners()

    def _round_corners(self) -> None:
        """Clip the window to a pill shape with the X SHAPE extension."""
        with contextlib.suppress(Exception):
            from Xlib import X, display
            from Xlib.ext import shape

            dpy = display.Display()
            if not dpy.has_extension('SHAPE'):
                return
            # Tk reports its inner window : climb to the real top-level one
            window = dpy.create_resource_object('window', self.winfo_id())
            root = dpy.screen().root
            while (parent := window.query_tree().parent) != root:
                window = parent
            radius = self.h / 2
            rects = []
            for y in range(self.h):
                dy = abs(y + 0.5 - radius)
                inset = round(radius - math.sqrt(max(radius**2 - dy**2, 0)))
                rects.append((inset, y, self.w - 2 * inset, 1))
            window.shape_rectangles(
                shape.SO.Set, shape.SK.Bounding, X.Unsorted, 0, 0, rects
            )
            dpy.flush()
            dpy.close()

    def render(
        self,
        mix: float,
        phase: float,
        levels: list[float],
        accent: tuple,
    ) -> None:
        """Draw one frame of the pill."""
        ss = SUPERSAMPLE
        u = self.scale * ss
        w, h = self.w * ss, self.h * ss
        img = Image.new('RGB', (w, h), BG)
        draw = ImageDraw.Draw(img)

        # Pill body + hairline border
        draw.rounded_rectangle(
            (0, 0, w - 1, h - 1),
            radius=h / 2,
            fill=BG,
            outline=BORDER,
            width=round(u),
        )

        # Pulsing halo around the badge while live
        cx, cy = self.badge_x * ss, h / 2
        r = 11 * u
        if mix > VISIBLE:
            pulse = (math.sin(phase) + 1) / 2
            halo_r = r + (1.5 + 2.5 * pulse) * u
            halo = _mix(BG, accent, 0.35 * mix * (1 - 0.5 * pulse))
            draw.ellipse(
                (cx - halo_r, cy - halo_r, cx + halo_r, cy + halo_r), fill=halo
            )

        # Microphone badge
        badge = _mix(BADGE_MUTED, accent, mix)
        icon = _mix(FG_MUTED, FG_LIVE, mix)
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=badge)
        self._draw_mic(draw, cx, cy, 5.5 * u, icon)
        if mix < 0.5:  # noqa: PLR2004
            # Slash for the muted state, with a gap cut in the badge color
            a, b = 5.5 * u, 5.5 * u
            slash = (cx - a, cy - b, cx + a, cy + b)
            draw.line(slash, fill=badge, width=round(3.2 * u))
            draw.line(slash, fill=icon, width=round(1.4 * u))

        # Level meter : rounded bars scrolling right to left
        bar_w, gap = 3 * u, 2 * u
        max_h, min_h = h - 16 * u, 3 * u
        bar_color = _mix(BARS_MUTED, FG_LIVE, mix)
        for i, level in enumerate(levels):
            x0 = self.bars_x * ss + i * (bar_w + gap)
            bh = min_h + (max_h - min_h) * level
            draw.rounded_rectangle(
                (x0, cy - bh / 2, x0 + bar_w, cy + bh / 2),
                radius=bar_w / 2,
                fill=bar_color,
            )

        # Optional label (voice effect)
        if self.text:
            color = _mix(FG_MUTED, FG_LIVE, mix)
            draw.text(
                (self.text_x * ss, cy),
                self.text,
                font=self.font,
                fill=color,
                anchor='lm',
            )

        self.photo.paste(img.resize((self.w, self.h), Image.Resampling.LANCZOS))

    @staticmethod
    def _draw_mic(
        draw: ImageDraw.ImageDraw, cx: float, cy: float, u: float, color: tuple
    ) -> None:
        """Draw a microphone glyph of half-size ``u`` centered on (cx, cy)."""
        stroke = max(1, round(u * 0.22))
        # Capsule
        draw.rounded_rectangle(
            (cx - 0.38 * u, cy - u, cx + 0.38 * u, cy + 0.25 * u),
            radius=0.38 * u,
            fill=color,
        )
        # Holder arc + stem + base
        draw.arc(
            (cx - 0.72 * u, cy - 0.55 * u, cx + 0.72 * u, cy + 0.6 * u),
            0, 180, fill=color, width=stroke,
        )
        draw.line((cx, cy + 0.6 * u, cx, cy + u), fill=color, width=stroke)
        base = (cx - 0.4 * u, cy + u, cx + 0.4 * u, cy + u)
        draw.line(base, fill=color, width=stroke)

    def start_move(self, event: tk.Event) -> None:
        """Record the grab point when the drag starts."""
        self.x = event.x
        self.y = event.y

    def stop_move(self, _event: tk.Event) -> None:
        """Clear the grab point when the drag ends."""
        self.x = None
        self.y = None

    def on_motion(self, event: tk.Event) -> None:
        """Move the overlay to follow the pointer during a drag."""
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.winfo_x() + deltax
        y = self.winfo_y() + deltay
        self.geometry(f'+{x}+{y}')
