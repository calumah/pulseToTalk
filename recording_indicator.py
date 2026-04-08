#!/usr/bin/env python
# coding: utf-8
#
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

import math
import tkinter as tk
from pulsectl import Pulse


class RecordingIndicator(tk.Tk):

    def __init__(self):
        super().__init__()

        # Remove root window to avoid two windows
        # See : https://stackoverflow.com/a/48289343/1079254
        self.withdraw()

        # Register overlay
        self.overlay = Overlay(self)

        # Init pulse (do not support multi-thread !)
        self.pulse = Pulse(self.__class__.__name__)

        self._phase = 0.0

    # Custom methods
    def active_recording(self):
        self._phase += 0.15
        brightness = (math.sin(self._phase) + 1) / 2  # 0.0 → 1.0
        r = int(180 + 55 * brightness)
        g = int(20 * (1 - brightness))
        b = int(20 * (1 - brightness))
        self.overlay.set_dot_color('#%02x%02x%02x' % (r, g, b))

    def inactive_recording(self):
        self._phase = 0.0
        self.overlay.set_dot_color('#3a3a3a')

    def start(self):
        """Start the periodic update loop using tkinter's scheduler."""
        self._schedule_update()

    def _schedule_update(self):
        self.do_update()
        self.after(100, self._schedule_update)

    def do_update(self):
        # Check status for recording indicator
        if self.is_sources_muted():
            self.inactive_recording()
        else:
            self.active_recording()

    def is_sources_muted(self):
        """Return False if at least one source is recording
        """
        for source in self.pulse.source_list():
            # Exclude monitors input
            if source.name.endswith('.monitor'):
                continue
            # mute = 0 mean recording
            if source.mute == 0:
                return False
        # No source recording found, all are muted
        return True


class Overlay(tk.Toplevel):

    SIZE = 36

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.overrideredirect(True)
        self.attributes('-topmost', True)

        self.geometry('%dx%d+%d+6' % (
            self.SIZE, self.SIZE,
            int(self.winfo_screenwidth() / 2)
        ))

        self.canvas = tk.Canvas(
            self,
            width=self.SIZE,
            height=self.SIZE,
            bg='#1a1a1a',
            highlightthickness=0
        )
        self.canvas.pack()

        pad = 8
        self.dot = self.canvas.create_oval(
            pad, pad,
            self.SIZE - pad, self.SIZE - pad,
            fill='#3a3a3a',
            outline=''
        )

        self.canvas.bind('<ButtonPress-1>', self.start_move)
        self.canvas.bind('<ButtonRelease-1>', self.stop_move)
        self.canvas.bind('<B1-Motion>', self.on_motion)

    def set_dot_color(self, color):
        self.canvas.itemconfig(self.dot, fill=color)

    def start_move(self, event):
        self.x = event.x
        self.y = event.y

    def stop_move(self, event):
        self.x = None
        self.y = None

    def on_motion(self, event):
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.winfo_x() + deltax
        y = self.winfo_y() + deltay
        self.geometry('+%s+%s' % (x, y))
