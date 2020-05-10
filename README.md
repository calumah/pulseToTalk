# pulseToTalk

Simple push to talk binding for X / Pulseaudio in user mode (command line only)

## Install / Download

Install python2 or python3 from your distribution

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

```
$ cd pulseToTalk/
$ pip install -r requirements.txt
$ ./setup.sh
```

./setup.sh will download and configure https://github.com/JeffHoogland/pyxhook repository

## Use

Choose binded key interactive way and start
```
$ ./pulseToTalk.py
```

Bind F12 and mouse_middle click key on start (you can list events codes with --debug and press any key)
```
$ ./pulseToTalk.py --debug --event_code f12 mouse_middle
```

Disable recording indicator
```
$ ./pulseToTalk.py --no_indicator
```

For help :
```
$ ./pulseToTalk.py -h
```

## License

This program comes with ABSOLUTELY NO WARRANTY. This is free software, and you are welcome to redistribute it under certain conditions.

## Authors

- Calumah
