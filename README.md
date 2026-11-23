# pulseToTalk

Simple **push-to-talk** for PulseAudio on a GNU/Linux desktop, in user mode (command line only).

Your microphone stays muted by default and is unmuted only while you hold your chosen key or mouse button — no more being heard when you did not mean to. No root access, no desktop-environment integration, no global config to edit.

## Features

- **Bind any key and/or mouse button** to activate your microphone while held (you can bind several at once).
- **Recording indicator**: a small draggable pill overlay whose badge shows the mic state (gray muted, red live, amber locked), with a live level meter while you talk (can be disabled).
- **Lock recording** hands-free with `Ctrl + <bound key>`, and unlock it the same way.
- **Target specific sources**: mute/unmute only the PulseAudio sources you choose, or all of them.
- **Works on X11 and Wayland**: default X11 backend, plus an optional `evdev` backend that reads input below the display server.
- **Runs entirely in user mode** — no root required.

## Requirements

- **PulseAudio**, or **PipeWire** with the PulseAudio compatibility layer (`pipewire-pulse`). Both are muted/unmuted transparently.
- A display server:
  - **X11** — works out of the box with the default `xhook` backend.
  - **Wayland** — use the `evdev` backend (see [Wayland](#wayland-evdev-backend) below).
- **Python ≥ 3.12**.
- [**uv**](https://docs.astral.sh/uv/) to manage the virtual environment and dependencies.

## Install

Clone the repository:
```
$ git clone https://github.com/calumah/pulseToTalk.git
$ cd pulseToTalk/
```

Then create the environment and install the dependencies:
```
$ uv sync
```

To also build the optional Wayland-capable `evdev` backend:
```
$ uv sync --extra evdev
```

## Usage

Start pulseToTalk and bind a key/button interactively — the first key or button you press after launch becomes the trigger:
```
$ uv run pulsetotalk
```

Bind keys up front, e.g. `F12` and the middle mouse button:
```
$ uv run pulsetotalk --event_code f12 mouse_middle
```

Bind the `scroll_lock` key:
```
$ uv run pulsetotalk --event_code scroll_lock
```

Disable the recording indicator overlay:
```
$ uv run pulsetotalk --no_indicator
```

Operate only on specific PulseAudio sources:
```
$ uv run pulsetotalk --sources alsa_input.pci-0000_2d_00.4.analog-stereo
```

Find the names of your keys, mouse buttons and sources by running with `--debug` and pressing keys / toggling the mute:
```
$ uv run pulsetotalk --debug --event_code f12 mouse_middle
```

For the full list of options:
```
$ uv run pulsetotalk -h
```

### Options

| Option | Description |
| --- | --- |
| `--event_code <key> [<key> ...]` | Key(s) and/or mouse button(s) to bind. If omitted, the first input pressed after launch is used. |
| `--no_indicator` | Do not show the recording indicator overlay. |
| `--sources <name> [<name> ...]` | Operate only on the given PulseAudio sources (default: all). |
| `--backend {xhook,evdev}` | Input backend: `xhook` (X11 only, default) or `evdev` (X11 + Wayland). See [Wayland](#wayland-evdev-backend). |
| `--debug` | Print debug output (key codes, source names, events). |

### Lock recording

Hold `Ctrl` and press a bound key to **lock** recording on: your microphone stays unmuted until you repeat `Ctrl + <bound key>` to unlock it. Useful for long calls where you do not want to keep a key held down.

Stop pulseToTalk at any time with `Ctrl + C`; all sources are unmuted again on exit.

### Wayland (evdev backend)

The default `xhook` backend relies on X11 global key hooks, which Wayland forbids by design. To use pulseToTalk under Wayland, switch to the `evdev` backend, which reads `/dev/input` directly — below the display server — so the same backend also works on X11.

Install the backend and grant read access to input devices (one-time setup, then re-login):
```
$ uv sync --extra evdev
$ sudo usermod -aG input $USER
```

Then run with `--backend evdev`:
```
$ uv run --extra evdev pulsetotalk --backend evdev --event_code f12
```

Notes:
- Key **names differ** between backends (e.g. Scroll Lock is `scroll_lock` under `xhook` but `scrolllock` under `evdev`). List the names your backend reports with `--debug`.
- The recording indicator runs through XWayland; it is displayed, but Wayland may restrict its position and always-on-top behaviour.

## License

GPL-3.0-or-later. This program comes with ABSOLUTELY NO WARRANTY. This is free software, and you are welcome to redistribute it under certain conditions. See [LICENSE](LICENSE).

## Authors / Contributors

- calumah
- sur5r
