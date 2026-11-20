"""pulseToTalk: push-to-talk microphone muting for PulseAudio / PipeWire."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version('pulsetotalk')
except PackageNotFoundError:  # not installed (e.g. run straight from a checkout)
    __version__ = 'unknown'

# Imported after __version__ so submodules can read it without a circular import.
from .app import PulseToTalk

__all__ = ['PulseToTalk', '__version__']
