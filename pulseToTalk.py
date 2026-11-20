#!/usr/bin/env python
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

"""Push-to-talk microphone muting for PulseAudio in user mode (CLI only)."""

import logging
import sys
import threading

import colorlog
from pulsectl import Pulse

from input_backends import InputEvent, make_backend
from recording_indicator import RecordingIndicator


class PulseToTalk:
    """Simple push to talk binding for X / Pulseaudio.

    Work in user mode (command line only)
    """

    def __init__(self, **kwargs: object) -> None:
        """Init all variables for pulseToTalk and save config.

        Kwargs :
            - event_code (list) : Bind key names list
                (optional) (default: None)
            - no_indicator (bool) : Do not show recording
                indicator (default: False)
            - sources (list) : Operate only on the given
                pulseaudio sources (default: None)
            - backend (str) : Input backend, 'xhook' (X11) or
                'evdev' (X11 + Wayland) (default: 'xhook')
            - debug (bool) : Activate debug mode (default: False)
        """
        self.config = kwargs

        # Init logger
        handler = logging.StreamHandler()
        handler.setFormatter(
            colorlog.ColoredFormatter(
                '[%(name)s]%(log_color)s %(levelname)s > %(message)s'
            )
        )
        self.logger = colorlog.getLogger(self.__class__.__name__)
        self.logger.addHandler(handler)
        if self.config.get('debug', False) is True:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.WARNING)

        # Version
        self.logger.debug('Starting version 1.3.1')

        # Create the input backend ('xhook' for X11, 'evdev' for X11 + Wayland).
        # It calls on_key_event() with a normalized InputEvent for every key /
        # mouse press and release; the thread is only started later, in run().
        backend_name = self.config.get('backend') or 'xhook'
        self.logger.debug(f'Using input backend : {backend_name}')
        self.backend = make_backend(backend_name, self.on_key_event)

        # Init pulse (do not support multi-thread !)
        self.pulse = Pulse(self.__class__.__name__)

        # Init empty recording indicator
        self.recording_indicator = None
        if self.config.get('no_indicator', False) is False:
            # Init RecordingIndicator
            self.recording_indicator = RecordingIndicator()

        # Store if recording is locked
        self.lock_recording = False
        # Store if control is keep pushed
        self.is_control_modifier = False

        # State of recording
        self.is_recording = False
        # Mute all inputs at start
        self.mute_sources()
        # Init custom variables
        self.stored_event_code = set()
        # If event code is passed by args
        if self.config.get('event_code'):
            self.stored_event_code = set(self.config['event_code'])
        # Start the input listener now that our state is ready
        self.backend.start()

        # Process stored_event_code
        self.logger.warning('Press CTRL + C to exit...')
        if len(self.stored_event_code) == 0:
            self.logger.debug('!!! Key binding not yet configured !')
            self.logger.critical('Press key/mouse to bind :')
        else:
            binds = ', '.join(self.stored_event_code)
            self.logger.critical(f'Configured bind(s) : {binds}')

    def run(self) -> None:
        """Run the main loop to watch user keys / mouse.

        The input backend runs in its own thread; this method just keeps the
        process alive. If the recording indicator is active, it delegates to
        tkinter's mainloop (so the indicator's X11 access stays on one thread);
        otherwise it blocks on a threading.Event until Ctrl + C.
        """
        try:
            if self.recording_indicator is not None:
                self.recording_indicator.start()
                self.recording_indicator.mainloop()
            else:
                threading.Event().wait()
        except KeyboardInterrupt:
            pass
        # Close the listener when we are done
        self.backend.stop()
        # Unmute all
        self.mute_sources(False)
        self.logger.debug('Terminated')

    def mute_sources(self, is_mute: bool = True) -> None:
        """Mute or unmute all audio sources with pulseaudio."""
        if is_mute:
            self.logger.info('Do source(s) MUTE :')
        else:
            self.logger.info('Do source(s) UNMUTE :')

        sources = self.config.get('sources')
        for source in self.pulse.source_list():

            # Exclude monitors input
            if source.name.endswith('.monitor'):
                continue

            # Mute only specified sources
            if sources and source.name not in sources:
                continue

            # Mute source
            self.pulse.mute(source, is_mute)

            self.logger.info(f'- {source}')

    def on_stored_event(self, event: InputEvent) -> None:
        """Switch mode if needed when one of the bound events is triggered."""
        # Toggle the recording lock when Ctrl is held and a bound key is pressed
        if self.is_control_modifier is True and event.is_down:
            self.lock_recording = not self.lock_recording

        # If lock_recording force recording until it's stopped
        # Normal activate recording on press
        if self.is_recording is False and (
            event.is_down or self.lock_recording is True
        ):
            self.is_recording = True
            self.mute_sources(is_mute=False)
        # Normal disable recording on release key
        elif self.is_recording is True and event.is_up and (
            self.lock_recording is False
        ):
            self.is_recording = False
            self.mute_sources()

    def on_key_event(self, event: InputEvent) -> None:
        """Handle a normalized InputEvent coming from the active backend."""
        self.logger.debug(f'Event detected : {event}')

        # Store key on first key to be used if no event previously registred
        if len(self.stored_event_code) == 0:
            self.stored_event_code.add(event.code)
            # Print binded event and stop here
            kind = 'MOUSE' if event.is_mouse else 'KEY'
            self.logger.critical(f"Binded {kind} event : '{event.code}'.")
            return

        # Check ctrl modifier key
        if event.is_ctrl:
            self.is_control_modifier = event.is_down

        # Trigger if event is the same as stored event
        if event.code in self.stored_event_code:
            self.on_stored_event(event)


if __name__ == '__main__':
    import argparse

    # Command line parser
    parser = argparse.ArgumentParser(description='pulseToTalk : \
Simple push to talk binding for X / Pulseaudio in \
user mode (command line only)')
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Print debug'
    )
    parser.add_argument(
        '--event_code',
        nargs='+',
        help='Choose key/mouse to bind (multiple choices allowed)'
    )
    parser.add_argument(
        '--no_indicator',
        action='store_true',
        help='Do not show recording indicator'
    )
    parser.add_argument(
        '--sources',
        nargs='+',
        help='Operate only on the given pulseaudio sources'
    )
    parser.add_argument(
        '--backend',
        choices=['xhook', 'evdev'],
        default='xhook',
        help='Input backend : xhook (X11 only, default) or '
             'evdev (X11 + Wayland, needs read access to /dev/input)'
    )
    args = parser.parse_args()

    # Print license info
    print('''This program comes with ABSOLUTELY NO WARRANTY.
This is free software, and you are welcome \
to redistribute it under certain conditions.''')

    # Run
    PulseToTalk(**vars(args)).run()

    sys.exit(0)
