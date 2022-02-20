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

import random
import tkinter as tk
from pulsectl import Pulse


class RecordingIndicator(tk.Tk):

    def __init__(self):
        super().__init__()

        # Remove root window to avoid two windows
        # See : https://stackoverflow.com/a/48289343/1079254
        self.withdraw()

        # Register overlay
        self.overlay = Overlay(
            self,
            cursor='hand1',
            borderwidth=2,
            relief='solid'
        )

        # Init pulse (do not support multi-thread !)
        self.pulse = Pulse(self.__class__.__name__)

        self.recording_color = [
            '#c4181a',
            '#f9df74',
            '#ea2b1f',
        ]

    # Custom methods
    def active_recording(self):
        self.overlay.icon.config(bg=random.choice(self.recording_color))

    def inactive_recording(self):
        self.overlay.icon.config(bg='grey')

    def do_update(self):
        # Check status for recording indicator
        if self.is_sources_muted():
            self.inactive_recording()
        else:
            self.active_recording()

        # Update tkinter window
        self.update_idletasks()
        self.update()

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.overrideredirect(True)

        # At start center on top
        self.geometry('40x40+%d+0' % (
            int(
                self.winfo_screenwidth() / 2
            )
        ))

        # Can be bind to label or whole overlay
        self.icon = tk.Label(
            self,
            text=u'[\u23FA]',
            height=5,
            width=10,
            font=('DejaVu', 12, 'bold')
        )
        self.icon.pack()

        self.bind('<ButtonPress-1>', self.start_move)
        self.bind('<ButtonRelease-1>', self.stop_move)
        self.bind('<B1-Motion>', self.on_motion)

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
