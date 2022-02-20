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

import time
import logging

import colorlog
import pyxhook
from pulsectl import Pulse

from recording_indicator import RecordingIndicator


class pulseToTalk:
    """Simple push to talk binding for X / Pulseaudio

    Work in user mode (command line only)
    """

    def __init__(self, **kwargs):
        """Init all variables for pulseToTalk and save config

        Kwargs :
            - event_code (list) : Bind key names list
                (optional) (default: None)
            - no_indicator (bool) : Do not show recording
                indicator (default: False)
            - sources (list) : Operate only on the given
                pulseaudio sources (default: None)
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
        self.logger.debug('Starting version 1.3')

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
        # Start listener
        self.hookman.start()
        # Init custom variables
        self.stored_event_code = set()
        # If event code is passed by args
        if self.config.get('event_code'):
            self.stored_event_code = set(self.config['event_code'])

        # Process stored_event_code
        self.logger.warning('Press CTRL + C to exit...')
        if len(self.stored_event_code) == 0:
            self.logger.debug('!!! Key binding not yet configured !')
            self.logger.critical('Press key/mouse to bind :')
        else:
            self.logger.critical('Configured bind(s) : %s' % ', '.join(
                self.stored_event_code
            ))

    def run(self):
        """Run infinite loop to watch user keys / mouse
        """
        try:
            # Create a loop to keep the application running
            while True:
                if self.recording_indicator is not None:
                    self.recording_indicator.do_update()
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        # Close the listener when we are done
        self.hookman.cancel()
        # Unmute all
        self.mute_sources(False)
        self.logger.debug('Terminated')

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

            # Mute only specified sources
            if self.config.get('sources') and source.name not in self.config.get('sources'):
                continue

            # Mute source
            self.pulse.mute(source, is_mute)

            self.logger.info('- %s' % source)

    def on_stored_event(self, event):
        """Switch mode if needed if one of stored event is trigger
        """
        # Lock recording if Ctrl is pressed once with event
        if self.is_control_modifier is True and self.is_event_down(event):
            if self.lock_recording is False:
                self.lock_recording = True
            else:
                self.lock_recording = False

        # If lock_recording force recording until it's stopped
        # Normal activate recording on press
        if self.is_recording is False and (
            self.is_event_down(event) or self.lock_recording is True
        ):
            self.is_recording = True
            self.mute_sources(is_mute=False)
        # Normal disable recording on release key
        elif self.is_recording is True and self.is_event_up(
                event
        ) and self.lock_recording is False:
            self.is_recording = False
            self.mute_sources()

    @staticmethod
    def get_event_code(event):
        """Return cleaned event code
        """
        # Try to detect if Mouse or Key are pressed
        if hasattr(event, 'Key') is True:
            return event.Key.lower()
        if hasattr(event, 'Position') is True:
            # Create mouse key without 'up' and 'down' like 'mouse_left'
            return '_'.join(event.MessageName.lower().split()[0:2])

        raise ValueError('Event not recognized : "%s" ' % event)

    @staticmethod
    def is_event_down(event):
        if event is None:
            return False
        return event.MessageName.endswith(' down')

    @staticmethod
    def is_event_up(event):
        if event is None:
            return False
        return event.MessageName.endswith(' up')

    def on_key_event(self, event):
        event_code = self.get_event_code(event)
        self.logger.debug('Event detected : %s %s' % (event, event_code))

        # Store key on first key to be used if no event previously registred
        if len(self.stored_event_code) == 0:

            self.stored_event_code.add(event_code)

            # Print binded event and exit function
            return self.logger.critical('Binded %s event : \'%s\'.' % (
                'KEY' if hasattr(event, 'Key')
                else 'MOUSE',
                event_code
            ))

        # Check ctrl modifier key
        if event_code in ['control_l', 'control_r']:
            if self.is_event_down(event):
                self.is_control_modifier = True
            else:
                self.is_control_modifier = False

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
    p = pulseToTalk(**vars(args)).run()

    exit(0)
