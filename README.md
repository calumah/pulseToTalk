# pulseToTalk

Simple push to talk binding for X / Pulseaudio in user mode (command line only)

## Features

- Choose any key/mouse button (can be both) to activate your microphone when you want.
- Recording indicator showing when sound is captured (can be disabled).
- Lock recording if needed by using Ctrl + <Key> (unlock same way).
- Run without root access.

## Install / Download

Install `python` >= 3.3 from your distribution.

Download and extract :
```
$ wget https://github.com/calumah/pulseToTalk/archive/master.zip
$ unzip master.zip
```

OR

```
$ git clone https://github.com/calumah/pulseToTalk.git
```

## Setup and dependencies

This project uses [uv](https://docs.astral.sh/uv/) to manage its virtual environment and dependencies.

From source:
```
$ cd pulseToTalk/
$ uv sync
```

## Use

Choose binded key interactive way and start
```
$ uv run ./pulseToTalk.py
```

For example you can bind F12 and `mouse_middle` click key on start (you can list events codes with `--debug` and press any key)
```
$ uv run ./pulseToTalk.py --debug --event_code f12 mouse_middle
```

Another example binding `scroll_lock` key
```
$ uv run ./pulseToTalk.py --event_code scroll_lock
```

Disable recording indicator
```
$ uv run ./pulseToTalk.py --no_indicator
```

Operate only on the given pulseaudio sources (you can list sources name with --debug when mute/unmute)

```
$ uv run ./pulseToTalk.py --sources alsa_input.pci-0000_2d_00.4.analog-stereo
```

For help :
```
$ uv run ./pulseToTalk.py -h
```

## License

This program comes with ABSOLUTELY NO WARRANTY. This is free software, and you are welcome to redistribute it under certain conditions.

## Authors/Contributors

- calumah
- sur5r
