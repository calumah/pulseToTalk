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

"""Command-line entry point for pulseToTalk."""

import argparse

from .app import PulseToTalk
from .voice import EFFECTS

LICENSE_NOTICE = (
    'This program comes with ABSOLUTELY NO WARRANTY.\n'
    'This is free software, and you are welcome to redistribute it '
    'under certain conditions.'
)


def main() -> None:
    """Parse command-line arguments and run pulseToTalk."""
    parser = argparse.ArgumentParser(
        description='pulseToTalk : Simple push to talk binding for X / '
        'Pulseaudio in user mode (command line only)',
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Print debug',
    )
    parser.add_argument(
        '--event_code',
        nargs='+',
        help='Choose key/mouse to bind (multiple choices allowed)',
    )
    parser.add_argument(
        '--no_indicator',
        action='store_true',
        help='Do not show recording indicator',
    )
    parser.add_argument(
        '--sources',
        nargs='+',
        help='Operate only on the given pulseaudio sources',
    )
    parser.add_argument(
        '--backend',
        choices=['xhook', 'evdev'],
        default='xhook',
        help='Input backend : xhook (X11 only, default) or '
        'evdev (X11 + Wayland, needs read access to /dev/input)',
    )
    parser.add_argument(
        '--voice',
        nargs='+',
        choices=list(EFFECTS),
        metavar='EFFECT',
        help='Transform your voice through a virtual mic. Effects are '
        f'chained in order (e.g. deep robot) : {", ".join(EFFECTS)}. '
        'Needs `uv sync --extra voice`',
    )
    parser.add_argument(
        '--voice_source',
        help='Real mic captured by --voice (default: first of --sources, '
        'else the default source)',
    )
    args = parser.parse_args()

    print(LICENSE_NOTICE)

    PulseToTalk(**vars(args)).run()


if __name__ == '__main__':
    main()
