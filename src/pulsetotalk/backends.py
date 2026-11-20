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

"""Input backends for pulseToTalk.

A backend watches the keyboard and mouse globally and calls a callback with a
normalized :class:`InputEvent` for every key/button press and release. The core
pulseToTalk logic never talks to Xlib or evdev directly, only to these events,
so switching backend does not touch the push-to-talk / lock / mute logic.

Two backends are provided:

- ``xhook`` : the historical X11 backend (pyxhook / Xlib). X11 sessions only.
- ``evdev`` : reads ``/dev/input`` directly, below the display server, so it
              works under both X11 and Wayland. Requires read access to
              ``/dev/input`` -- add your user to the ``input`` group with
              ``sudo usermod -aG input $USER`` and re-login.

Key *names* differ between backends (e.g. the Scroll Lock key is ``scroll_lock``
under xhook but ``scrolllock`` under evdev). Discover the names your backend
reports by running pulseToTalk with ``--debug`` and pressing the key.
"""

import contextlib
import threading
from collections.abc import Callable
from typing import ClassVar


class InputEvent:
    """A normalized keyboard/mouse event, independent of the backend.

    Attributes:
        code (str): Normalized name, e.g. ``'f12'``, ``'scrolllock'`` or
            ``'mouse_middle'``.
        is_mouse (bool): True for mouse buttons, False for keyboard keys.
        is_down (bool): True on press.
        is_up (bool): True on release.
        is_ctrl (bool): True for the left/right Control keys (used for the
            Ctrl + key recording lock).
    """

    __slots__ = ('code', 'is_ctrl', 'is_down', 'is_mouse', 'is_up')

    def __init__(
        self,
        code: str,
        is_mouse: bool,
        is_down: bool,
        is_up: bool,
        is_ctrl: bool,
    ) -> None:
        """Store the normalized event fields (see the class docstring)."""
        self.code = code
        self.is_mouse = is_mouse
        self.is_down = is_down
        self.is_up = is_up
        self.is_ctrl = is_ctrl

    def __repr__(self) -> str:
        """Return a compact, human-readable representation for logs."""
        direction = 'down' if self.is_down else 'up' if self.is_up else '?'
        kind = 'MOUSE' if self.is_mouse else 'KEY'
        return f'InputEvent({kind} {direction} {self.code!r})'


# A backend reports every press/release by calling this with an InputEvent.
EventCallback = Callable[[InputEvent], None]


class XHookBackend:
    """Historical X11 backend built on pyxhook / Xlib (X11 sessions only)."""

    CTRL_CODES: ClassVar[set[str]] = {'control_l', 'control_r'}

    def __init__(self, on_event: EventCallback) -> None:
        """Hook the keyboard and mouse through pyxhook (listener not started)."""
        import pyxhook

        self._on_event = on_event
        self.hookman = pyxhook.HookManager()

        # Disable pyxhook's per-event focused-window lookup.
        #
        # pulseToTalk only ever reads event.Key / event.MessageName /
        # event.Position, never the focused-window metadata. Yet pyxhook calls
        # xwindowinfo() on *every* key/mouse event, which does an X round-trip
        # (local_dpy.get_input_focus()) wrapped in a bare `except:`.
        #
        # On python-xlib 0.33 (Python 3.13+), an exception escaping
        # send_and_recv() during that round-trip leaves the display's internal
        # recv_active flag set; pyxhook swallows the exception, and every
        # subsequent use of the display then busy-loops at 100% CPU forever
        # (see keyd issue #1329). This is triggered in the wild when the focused
        # window - often belonging to another process that is closing - makes
        # the X request fail. Stubbing this out removes both the trigger and the
        # needless per-event round-trip.
        self.hookman.xwindowinfo = lambda: {
            'name': None, 'class': None, 'handle': None
        }

        # Fire our callback on every key / mouse press and release
        self.hookman.KeyDown = self._handle
        self.hookman.KeyUp = self._handle
        self.hookman.MouseAllButtonsDown = self._handle
        self.hookman.MouseAllButtonsUp = self._handle
        self.hookman.HookKeyboard()

    def _handle(self, event: object) -> None:
        """Translate a raw pyxhook event into an InputEvent and dispatch it."""
        if hasattr(event, 'Key'):
            code = event.Key.lower()
            is_mouse = False
        else:
            # Build a mouse code without 'up'/'down', e.g. 'mouse_left'
            code = '_'.join(event.MessageName.lower().split()[0:2])
            is_mouse = True

        self._on_event(InputEvent(
            code=code,
            is_mouse=is_mouse,
            is_down=event.MessageName.endswith(' down'),
            is_up=event.MessageName.endswith(' up'),
            is_ctrl=code in self.CTRL_CODES,
        ))

    def start(self) -> None:
        """Start the pyxhook listener thread."""
        self.hookman.start()

    def stop(self) -> None:
        """Stop the pyxhook listener thread."""
        self.hookman.cancel()


class EvdevBackend:
    """Backend reading /dev/input directly (works on X11 *and* Wayland).

    Events are read passively (devices are never grabbed), so other
    applications keep receiving input normally.
    """

    CTRL_CODES: ClassVar[set[str]] = {'leftctrl', 'rightctrl'}

    def __init__(self, on_event: EventCallback) -> None:
        """Open the readable input devices (listener thread not started)."""
        import evdev
        from evdev import ecodes

        self._evdev = evdev
        self._ecodes = ecodes
        self._on_event = on_event
        self._stop = threading.Event()
        self._thread = None

        # Deterministic names for the common mouse buttons. Several BTN_*
        # aliases can share a code (e.g. BTN_LEFT / BTN_MOUSE), so pin them here
        # rather than relying on reverse-lookup ordering.
        self._mouse = {
            ecodes.BTN_LEFT: 'mouse_left',
            ecodes.BTN_RIGHT: 'mouse_right',
            ecodes.BTN_MIDDLE: 'mouse_middle',
            ecodes.BTN_SIDE: 'mouse_side',
            ecodes.BTN_EXTRA: 'mouse_extra',
        }

        self._devices = self._open_devices()
        if not self._devices:
            msg = (
                'evdev backend: no readable input device found. '
                'Add your user to the "input" group '
                '(sudo usermod -aG input $USER) and re-login.'
            )
            raise RuntimeError(msg)

    def _open_devices(self) -> list:
        """Open every input device that reports keys or buttons."""
        devices = []
        for path in self._evdev.list_devices():
            try:
                dev = self._evdev.InputDevice(path)
            except (PermissionError, OSError):
                # No read access (missing 'input' group) or transient error
                continue
            if self._ecodes.EV_KEY in dev.capabilities():
                devices.append(dev)
            else:
                dev.close()
        return devices

    @property
    def device_names(self) -> list[str]:
        """Names of the input devices currently being watched."""
        return [dev.name for dev in self._devices]

    @staticmethod
    def _first_name(name: str | list[str] | None) -> str | None:
        """Return a single code name, picking the first of any aliases."""
        if name is None:
            return None
        if isinstance(name, (list, tuple)):
            return name[0]
        return name

    def _code_for(self, code: int) -> tuple[str | None, bool]:
        """Map an evdev key code to a (normalized_name, is_mouse) pair."""
        if code in self._mouse:
            return self._mouse[code], True

        name = self._first_name(self._ecodes.BTN.get(code))
        if name is not None:
            return 'mouse_' + name[4:].lower(), True  # strip 'BTN_'

        name = self._first_name(self._ecodes.KEY.get(code))
        if name is not None:
            # 'KEY_F12' -> 'f12', 'KEY_SCROLLLOCK' -> 'scrolllock'
            return name.removeprefix('KEY_').lower(), False

        return None, False

    def _dispatch(self, ev: object) -> None:
        """Filter and translate one raw evdev event into an InputEvent."""
        if ev.type != self._ecodes.EV_KEY:
            return
        # value: 0 = release, 1 = press, 2 = autorepeat (ignored on purpose so
        # held keys do not flap the Ctrl lock or re-trigger recording)
        if ev.value not in (0, 1):
            return

        code, is_mouse = self._code_for(ev.code)
        if code is None:
            return

        is_down = ev.value == 1
        self._on_event(InputEvent(
            code=code,
            is_mouse=is_mouse,
            is_down=is_down,
            is_up=not is_down,
            is_ctrl=code in self.CTRL_CODES,
        ))

    def _run(self) -> None:
        """Read events from all devices until stop() is called."""
        import selectors

        sel = selectors.DefaultSelector()
        for dev in self._devices:
            sel.register(dev, selectors.EVENT_READ)
        try:
            while not self._stop.is_set():
                for key, _ in sel.select(timeout=0.5):
                    dev = key.fileobj
                    try:
                        for ev in dev.read():
                            self._dispatch(ev)
                    except OSError:
                        # Device unplugged: stop watching it
                        with contextlib.suppress(KeyError):
                            sel.unregister(dev)
        finally:
            sel.close()
            for dev in self._devices:
                with contextlib.suppress(OSError):
                    dev.close()

    def start(self) -> None:
        """Start the background device-reading thread."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the reading thread to stop and wait for it to finish."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)


BACKENDS = {
    'xhook': XHookBackend,
    'evdev': EvdevBackend,
}


def make_backend(name: str, on_event: EventCallback) -> XHookBackend | EvdevBackend:
    """Instantiate a backend by name, with friendly errors on missing deps."""
    try:
        backend_cls = BACKENDS[name]
    except KeyError:
        choices = ', '.join(sorted(BACKENDS))
        msg = f'Unknown backend {name!r} (choose from {choices})'
        raise ValueError(msg) from None

    try:
        return backend_cls(on_event)
    except ImportError as exc:
        if name == 'evdev':
            msg = (
                "evdev backend requires the 'evdev' package: "
                'install it with `uv sync --extra evdev`.'
            )
            raise RuntimeError(msg) from exc
        raise
