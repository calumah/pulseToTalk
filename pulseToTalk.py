#!/usr/bin/python
# coding: utf-8
#
# Copyright (C) 2017
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

# Logger
import colorlog
import logging
handler = logging.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter('%(log_color)s%(message)s'))
logger = colorlog.getLogger('pulseToTalk')
logger.addHandler(handler)
logger.setLevel(logging.CRITICAL)


class pulseToTalk(object):
    """ Simple push to talk binding for X / Pulseaudio
    Work in user mode (command line only)
    """

    def __init__(self, stored_event_code=None):
        """ Init all variables for pulseToTalk
        """

        logger.debug('# pulseToTalk v1.1')

        # Create hookmanager
        self.hookman = pyxhook.HookManager()
        # Define our callback to fire when a key / mouse is pressed or released
        self.hookman.KeyDown = self.on_key_event
        self.hookman.KeyUp = self.on_key_event
        self.hookman.MouseAllButtonsDown = self.on_key_event
        self.hookman.MouseAllButtonsUp = self.on_key_event
        # Hook the keyboard
        self.hookman.HookKeyboard()

        # Init pulse
        self.pulse = Pulse('pulseToTalk')
        # State of recording
        self.is_recording = False
        # Mute all inputs at start
        self.mute_sources()
        # Start listener
        self.hookman.start()
        # Init custom variables
        self.stored_event_code = set()
        if stored_event_code:
            self.stored_event_code = set(stored_event_code)

        # Process stored_event_code
        logger.warning('> Press CTRL + C to exit...')
        if len(self.stored_event_code) == 0:
            logger.debug('!!! Key binding not yet configured !')
            logger.critical('> Press key/mouse to bind :')
        else:
            logger.critical('Configured bind(s) : %s' % ', '.join(
                self.stored_event_code
            ))

        # Finally run
        self.run()

    def run(self):
        """ Run infinite loop to watch user keys / mouse
        """
        try:
            # Create a loop to keep the application running
            while True:
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass
        # Close the listener when we are done
        self.hookman.cancel()
        # Unmute all
        self.mute_sources(False)
        logger.debug('# pulseToTalk terminated.')

    def mute_sources(self, is_mute=True):
        """ Mute or unmute all audio sources with pulseaudio
        """

        if is_mute:
            logger.warning('Source(s) mute :')
        else:
            logger.warning('Source(s) unmute :')

        for source in self.pulse.source_list():

            # Exclude monitors input
            if source.name.endswith('.monitor'):
                continue
            # Mute source
            self.pulse.mute(source, is_mute)

            logger.warning(source)

    def on_stored_event(self, event):
        """ Switch mode if needed if one of stored event is trigger
        """
        if not self.is_recording and event.MessageName.endswith(' down'):
            self.is_recording = True
            self.mute_sources(is_mute=False)

        elif self.is_recording and event.MessageName.endswith(' up'):
            self.is_recording = False
            self.mute_sources()

    def get_event_code(self, event):
        """ Return cleaned event code
        """
        if isinstance(event, pyxhook.pyxhookkeyevent):
            return event.Key.lower()

        if isinstance(event, pyxhook.pyxhookmouseevent):
            # Create mouse key without 'up' and 'down' like 'mouse_left'
            return '_'.join(event.MessageName.lower().split()[0:2])

        raise ValueError('Event not recognized : "%s" ' % event)

    def on_key_event(self, event):

        event_code = self.get_event_code(event)
        logger.debug('Event detected : %s' % event_code)

        # Store key on first key to be used if no event previously registred
        if len(self.stored_event_code) == 0:

            self.stored_event_code.add(event_code)

            # Print binded event and exit function
            return logger.critical('Binded %s event : \'%s\'.' % (
                'KEY' if isinstance(event, pyxhook.pyxhookkeyevent)
                else 'MOUSE',
                event_code
            ))

        # Trigger if event is the same are
        if event_code in self.stored_event_code:
            self.on_stored_event(event)


if __name__ == '__main__':
    import argparse
    # Command line parser
    parser = argparse.ArgumentParser(description='pulseToTalk : \
Simple push to talk binding for X / Pulseaudio in \
user mode (command line only)')
    parser.add_argument('--debug', action='store_true', help='Print debug')
    parser.add_argument(
        '--event_code',
        nargs='+',
        help='Choose key/mouse to bind (multiple choice allowed)'
    )
    args = parser.parse_args()
    # Debug level
    if args.debug:
        logger.setLevel(logging.DEBUG)
    # Print license info
    logger.info('''This program comes with ABSOLUTELY NO WARRANTY.
This is free software, and you are welcome \
to redistribute it under certain conditions.''')
    # Run
    p = pulseToTalk(stored_event_code=args.event_code)
    exit(0)