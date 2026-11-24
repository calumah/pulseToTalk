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

"""JSON configuration file holding default command-line options.

The file uses the same names as the command-line options, e.g.::

    {
        "event_code": ["f12", "mouse_middle"],
        "backend": "evdev",
        "voice": ["robot"]
    }

Options given on the command line take precedence over the file.
"""

import json
from pathlib import Path

from .backends import BACKENDS
from .voice import EFFECTS

DEFAULT_PATH = Path.home() / '.pulseToTalk.json'

# Option name -> (expected type, allowed values or None)
SCHEMA: dict[str, tuple[type, tuple[str, ...] | None]] = {
    'event_code': (list, None),
    'sources': (list, None),
    'voice': (list, tuple(EFFECTS)),
    'voice_source': (str, None),
    'backend': (str, tuple(BACKENDS)),
    'no_indicator': (bool, None),
    'debug': (bool, None),
}


class ConfigError(Exception):
    """Raised when the configuration file cannot be used."""


def _validate(options: object, path: Path) -> dict:
    """Check option names, types and allowed values."""
    if not isinstance(options, dict):
        msg = f'{path}: expected a JSON object {{"option": value, ...}}'
        raise ConfigError(msg)
    for name, value in options.items():
        if name not in SCHEMA:
            known = ', '.join(SCHEMA)
            msg = f'{path}: unknown option "{name}" (known: {known})'
            raise ConfigError(msg)
        kind, allowed = SCHEMA[name]
        if kind is list:
            ok = isinstance(value, list) and all(isinstance(v, str) for v in value)
            values = value if ok else []
        else:
            ok = isinstance(value, kind)
            values = [value] if ok and kind is str else []
        if not ok:
            expected = 'a list of strings' if kind is list else kind.__name__
            msg = f'{path}: "{name}" must be {expected}'
            raise ConfigError(msg)
        if allowed:
            bad = [v for v in values if v not in allowed]
            if bad:
                msg = (
                    f'{path}: invalid "{name}" value(s) {", ".join(bad)} '
                    f'(choose from {", ".join(allowed)})'
                )
                raise ConfigError(msg)
    return options


def load_config(path: Path, *, required: bool = False) -> dict:
    """Load and validate the configuration file.

    Args:
        path: File to read.
        required: If False, a missing file yields an empty configuration.
    """
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        if required:
            msg = f'{path}: file not found'
            raise ConfigError(msg) from None
        return {}
    except OSError as exc:
        msg = f'{path}: {exc.strerror}'
        raise ConfigError(msg) from exc
    try:
        options = json.loads(text)
    except json.JSONDecodeError as exc:
        msg = f'{path}: invalid JSON ({exc})'
        raise ConfigError(msg) from exc
    return _validate(options, path)


def save_config(path: Path, options: dict) -> None:
    """Write the given options to the configuration file."""
    path.write_text(json.dumps(options, indent=4) + '\n', encoding='utf-8')
