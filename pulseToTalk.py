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

# Python 2/3 compatible
from __future__ import absolute_import, division, print_function
import time
from pulsectl import Pulse
from pyxhook import pyxhook
from recording_indicator import RecordingIndicator

import colorlog
import logging


class pulseToTalk(object):
    """Simple push to talk binding for X / Pulseaudio

    Work in user mode (command line only)
    """

    def __init__(self, event_code=None, no_indicator=False, debug=False, sources=None):
        """Init all variables for pulseToTalk

        Args :
            - event_code (list) : Bind key names list (optional)
            - no_indicator (book) : Do not show recording indicator
            - debug (bool) : Activate debug mode
            - sources (list) : Operate only on the given pulseaudio sources
        """

        # Init logger
        handler = logging.StreamHandler()
        handler.setFormatter(
            colorlog.ColoredFormatter('%(log_color)s%(message)s')
        )
        self.logger = colorlog.getLogger(self.__class__.__name__)
        self.logger.addHandler(handler)
        if debug:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.WARNING)

        self.sources = sources

        # Version
        self.logger.debug('[%s] Starting version 1.2' % (
            self.__class__.__name__
        ))

        # Create hookmanager
        self.hookman = pyxhook.HookManager()
        # Define our callback to fire when a key / mouse is pressed or released
        self.hookman.KeyDown = self.on_key_event
        self.hookman.KeyUp = self.on_key_event
        self.hookman.MouseAllButtonsDown = self.on_key_event
        self.hookman.MouseAllButtonsUp = self.on_key_event
        # Hook the keyboard
        self.hookman.HookKeyboard()

        # Init pulse (do not support multi-thread !)
        self.pulse = Pulse(self.__class__.__name__)

        self.no_indicator = no_indicator
        if self.no_indicator is False:
            # Init RecordingIndicator
            self.recording_indicator = RecordingIndicator()

        # State of recording
        self.is_recording = False
        # Mute all inputs at start
        self.mute_sources()
        # Start listener
        self.hookman.start()
        # Init custom variables
        self.stored_event_code = set()
        # If event code is passed by args
        if event_code:
            self.stored_event_code = set(event_code)

        # Process stored_event_code
        self.logger.warning('> Press CTRL + C to exit...')
        if len(self.stored_event_code) == 0:
            self.logger.debug('!!! Key binding not yet configured !')
            self.logger.critical('> Press key/mouse to bind :')
        else:
            self.logger.critical('Configured bind(s) : %s' % ', '.join(
                self.stored_event_code
            ))

        # Finally run
        self.run()

    def run(self):
        """Run infinite loop to watch user keys / mouse
        """
        try:
            # Create a loop to keep the application running
            while True:
                if self.no_indicator is False:
                    self.recording_indicator.do_update()
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        # Close the listener when we are done
        self.hookman.cancel()
        # Unmute all
        self.mute_sources(False)
        self.logger.debug('[%s] terminated.' % self.__class__.__name__)

    def mute_sources(self, is_mute=True):
        """Mute or unmute all audio sources with pulseaudio
        """

        if is_mute:
            self.logger.info('Do source(s) MUTE :')
        else:
            self.logger.info('Do source(s) UNMUTE :')

        for source in self.pulse.source_list():

            # Exclude monitors input
            if source.name.endswith('.monitor'):
                continue
            if self.sources and source.name not in self.sources:
                continue

            # Mute source
            self.pulse.mute(source, is_mute)

            self.logger.info('- %s' % source)

    def on_stored_event(self, event):
        """Switch mode if needed if one of stored event is trigger
        """
        if not self.is_recording and event.MessageName.endswith(' down'):
            self.is_recording = True
            self.mute_sources(is_mute=False)

        elif self.is_recording and event.MessageName.endswith(' up'):
            self.is_recording = False
            self.mute_sources()

    def get_event_code(self, event):
        """Return cleaned event code
        """
        if isinstance(event, pyxhook.pyxhookkeyevent):
            return event.Key.lower()

        if isinstance(event, pyxhook.pyxhookmouseevent):
            # Create mouse key without 'up' and 'down' like 'mouse_left'
            return '_'.join(event.MessageName.lower().split()[0:2])

        raise ValueError('Event not recognized : "%s" ' % event)

    def on_key_event(self, event):

        event_code = self.get_event_code(event)
        self.logger.debug('Event detected : %s' % event_code)

        # Store key on first key to be used if no event previously registred
        if len(self.stored_event_code) == 0:

            self.stored_event_code.add(event_code)

            # Print binded event and exit function
            return self.logger.critical('Binded %s event : \'%s\'.' % (
                'KEY' if isinstance(event, pyxhook.pyxhookkeyevent)
                else 'MOUSE',
                event_code
            ))

        # Trigger if event is the same as stored event
        if event_code in self.stored_event_code:
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
    args = parser.parse_args()

    # Print license info
    print('''This program comes with ABSOLUTELY NO WARRANTY.
This is free software, and you are welcome \
to redistribute it under certain conditions.''')

    # Run
    p = pulseToTalk(**vars(args))

    exit(0)
