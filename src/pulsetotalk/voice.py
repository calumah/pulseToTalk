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

"""Real-time voice changer feeding a virtual PulseAudio microphone.

Audio path::

    real mic --parec--> effects (numpy) --pacat--> null sink "pulsetotalk_voice"
                                                     |
                               remap source "pulsetotalk_mic" (virtual mic)

The virtual mic is made the default source while pulseToTalk runs, so apps
that follow the default pick up the transformed voice. Push-to-talk keeps
working unchanged: muting the real mic makes ``parec`` read silence, and the
virtual mic is itself muted/unmuted like any other source.

Requires the optional ``numpy`` dependency (``uv sync --extra voice``) and the
``parec`` / ``pacat`` tools shipped with PulseAudio / pipewire-pulse.
"""

import contextlib
import fcntl
import logging
import math
import os
import shutil
import subprocess
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    from pulsectl import Pulse

SINK_NAME = 'pulsetotalk_voice'
SOURCE_NAME = 'pulsetotalk_mic'
RATE = 48000
BLOCK = 480  # 10 ms of mono audio per processing block
LATENCY_MSEC = 20
# Audio allowed to wait for processing before stale blocks are dropped
MAX_QUEUED_BLOCKS = 2


def _numpy() -> 'np':  # type: ignore[name-defined]
    """Import numpy lazily, with a friendly error when it is missing."""
    try:
        import numpy
    except ImportError as exc:
        msg = (
            "voice effects require the 'numpy' package: "
            'install it with `uv sync --extra voice`.'
        )
        raise RuntimeError(msg) from exc
    return numpy


# --------------------------------------------------------------------------
# Effects : each one is stateful and processes one mono float32 block at a time
# --------------------------------------------------------------------------


class Robot:
    """Ring modulation plus a short metallic comb filter (Dalek-like)."""

    def __init__(self, freq: float = 50.0, comb_ms: float = 10.0) -> None:
        """Set the ring-modulation frequency and the comb delay."""
        self.np = _numpy()
        self.step = 2 * math.pi * freq / RATE
        self.phase = 0.0
        # Feedback comb : delay must be >= BLOCK to vectorize per block
        self.delay = max(BLOCK, int(RATE * comb_ms / 1000))
        self.feedback = 0.45
        self.history = self.np.zeros(self.delay, dtype=self.np.float32)

    def process(self, x: 'np.ndarray') -> 'np.ndarray':
        """Apply the effect to one block."""
        np = self.np
        n = len(x)
        phases = self.phase + self.step * np.arange(n)
        self.phase = (self.phase + self.step * n) % (2 * math.pi)
        y = 1.6 * x * np.sin(phases)
        # y[i] += feedback * out[i - delay]
        y = y + self.feedback * self.history[:n]
        self.history = np.concatenate((self.history[n:], y)).astype(np.float32)
        return y


class PitchShift:
    """Delay-line pitch shifter with two cross-faded read heads.

    ``ratio`` < 1 lowers the voice, > 1 raises it. Formants move with the
    pitch, which gives the classic "monster" / "chipmunk" sound.
    """

    def __init__(self, ratio: float, window_ms: float = 40.0) -> None:
        """Set the pitch ratio and the size of the delay window."""
        self.np = _numpy()
        self.window = int(RATE * window_ms / 1000)
        self.inc = (1.0 - ratio) / self.window
        self.phase = 0.0
        self.history = self.np.zeros(self.window + 2, dtype=self.np.float32)

    def process(self, x: 'np.ndarray') -> 'np.ndarray':
        """Apply the effect to one block."""
        np = self.np
        n = len(x)
        h = len(self.history)
        buf = np.concatenate((self.history, x))
        self.history = buf[-h:]

        phases = (self.phase + self.inc * np.arange(1, n + 1)) % 1.0
        self.phase = float(phases[-1])
        now = h + np.arange(n)
        out = np.zeros(n, dtype=np.float32)
        for head in (phases, (phases + 0.5) % 1.0):
            pos = now - head * self.window
            i0 = np.floor(pos).astype(np.int64)
            frac = pos - i0
            i1 = np.minimum(i0 + 1, len(buf) - 1)
            sample = buf[i0] * (1 - frac) + buf[i1] * frac
            # sin² windows of the two heads (offset by half) sum to 1
            out += sample * np.sin(math.pi * head) ** 2
        return out


def _is_silent(x: 'np.ndarray') -> bool:
    """Return True for an all-zero block (what a muted source delivers)."""
    return not x.any()


class FIR:
    """Stateful windowed-sinc FIR filter (low-pass, high-pass or band-pass).

    ``low`` = 0 gives a low-pass at ``high``; ``high`` = None a high-pass.
    """

    def __init__(
        self, low: float = 0.0, high: float | None = None, taps: int = 129
    ) -> None:
        """Design the filter kernel."""
        np = self.np = _numpy()
        t = np.arange(taps) - (taps - 1) / 2

        def lowpass(cut: float) -> 'np.ndarray':
            return 2 * cut / RATE * np.sinc(2 * cut / RATE * t)

        upper = lowpass(high) if high else (t == 0).astype(float)
        lower = lowpass(low) if low else 0
        self.kernel = ((upper - lower) * np.hamming(taps)).astype(np.float32)
        self.tail = np.zeros(taps - 1, dtype=np.float32)

    def process(self, x: 'np.ndarray') -> 'np.ndarray':
        """Filter one block."""
        np = self.np
        buf = np.concatenate((self.tail, x))
        self.tail = buf[-len(self.tail) :]
        return np.convolve(buf, self.kernel, mode='valid')


class ModDelay:
    """Delay line whose delay is swept by a sine LFO (chorus / vibrato).

    ``wet`` only with ``dry`` = 0 gives a vibrato, a mix gives a chorus.
    """

    def __init__(
        self,
        base_ms: float,
        depth_ms: float,
        rate_hz: float,
        wet: float = 1.0,
        dry: float = 0.0,
    ) -> None:
        """Set the delay sweep (``base_ms`` ± ``depth_ms`` at ``rate_hz``)."""
        np = self.np = _numpy()
        self.base = base_ms * RATE / 1000
        self.depth = depth_ms * RATE / 1000
        self.step = 2 * math.pi * rate_hz / RATE
        self.phase = 0.0
        self.wet, self.dry = wet, dry
        self.history = np.zeros(int(self.base + self.depth) + 2, dtype=np.float32)

    def process(self, x: 'np.ndarray') -> 'np.ndarray':
        """Apply the effect to one block."""
        np = self.np
        n, h = len(x), len(self.history)
        buf = np.concatenate((self.history, x))
        self.history = buf[-h:]
        phases = self.phase + self.step * np.arange(n)
        self.phase = (self.phase + self.step * n) % (2 * math.pi)
        pos = h + np.arange(n) - (self.base + self.depth * np.sin(phases))
        i0 = np.floor(pos).astype(np.int64)
        frac = pos - i0
        delayed = buf[i0] * (1 - frac) + buf[i0 + 1] * frac
        return self.dry * x + self.wet * delayed


class Chain:
    """Several effects applied in series, exposed as one effect."""

    def __init__(self, *effects: object) -> None:
        """Keep the effects to apply, in order."""
        self.effects = effects

    def on_release(self) -> None:
        """Forward the push-to-talk release to the effects that use it."""
        for effect in self.effects:
            if hasattr(effect, 'on_release'):
                effect.on_release()

    def process(self, x: 'np.ndarray') -> 'np.ndarray':
        """Apply every effect in turn."""
        for effect in self.effects:
            x = effect.process(x)
        return x


class Radio:
    """Walkie-talkie: band-limited, overdriven, hissy, with a squelch tail.

    When the transmission ends (push-to-talk released, see
    :meth:`on_release`), a short "kshhh" burst of noise is played.
    """

    SQUELCH_S = 0.28

    def __init__(self) -> None:
        """Build the band-pass and the noise generator."""
        np = self.np = _numpy()
        self.band = FIR(300, 3000)
        self.rng = np.random.default_rng()
        self.squelch_len = int(self.SQUELCH_S * RATE)
        self.squelch_left = 0

    def on_release(self) -> None:
        """Start the end-of-transmission squelch burst."""
        self.squelch_left = self.squelch_len

    def process(self, x: 'np.ndarray') -> 'np.ndarray':
        """Apply the effect to one block."""
        np = self.np
        n = len(x)
        noise = np.zeros(n, dtype=np.float32)
        if not _is_silent(x):
            noise += 0.004 * self.rng.standard_normal(n)  # Background hiss
        if self.squelch_left > 0:
            done = self.squelch_len - self.squelch_left
            t = (done + np.arange(n)) / self.squelch_len
            envelope = np.clip(1 - t, 0, 1) ** 2
            noise += 0.2 * envelope * self.rng.standard_normal(n)
            self.squelch_left -= n
        y = self.band.process(1.5 * x + noise)
        return 0.45 * np.tanh(3 * y)


class Underwater:
    """Very strong low-pass plus a slow, deep chorus for a floating feel."""

    def __init__(self) -> None:
        """Build the low-pass and the chorus."""
        self.np = _numpy()
        self.lowpass = FIR(0, 500, taps=401)
        self.chorus = ModDelay(18, 8, 0.5, wet=0.7, dry=0.7)
        self.wobble = ModDelay(6, 2, 0.23, wet=1.0)

    def process(self, x: 'np.ndarray') -> 'np.ndarray':
        """Apply the effect to one block."""
        y = self.chorus.process(self.lowpass.process(x))
        return 1.6 * self.wobble.process(y)


class Cathedral:
    """Large-hall reverb (Schroeder / Freeverb style, ~3.5 s decay).

    Every delay is at least one block long, so each block can be computed in
    one vectorized step from the past output only.
    """

    # Freeverb comb / allpass lengths rescaled to 48 kHz (allpass stretched
    # to >= BLOCK so they can be vectorized too)
    COMBS = (1695, 1760, 1623, 1548, 1390, 1476, 1293, 1215)
    ALLPASSES = (487, 613, 751)
    FEEDBACK = 0.93
    DAMP = 0.35  # High-frequency damping in the comb feedback
    ALLPASS_GAIN = 0.5
    PREDELAY_MS = 25
    INPUT_GAIN = 0.08  # Into each comb
    WET, DRY = 0.9, 0.7

    def __init__(self) -> None:
        """Allocate the delay lines."""
        np = self.np = _numpy()
        if min(self.ALLPASSES + self.COMBS) < BLOCK:
            msg = 'Reverb delays must be at least one block long'
            raise ValueError(msg)
        self.combs = [np.zeros(d + 1, dtype=np.float32) for d in self.COMBS]
        self.ap_in = [np.zeros(d, dtype=np.float32) for d in self.ALLPASSES]
        self.ap_out = [np.zeros(d, dtype=np.float32) for d in self.ALLPASSES]
        self.predelay = np.zeros(
            max(BLOCK, int(self.PREDELAY_MS * RATE / 1000)), dtype=np.float32
        )

    def process(self, x: 'np.ndarray') -> 'np.ndarray':
        """Apply the effect to one block."""
        np = self.np
        n = len(x)
        # Pre-delay
        buf = np.concatenate((self.predelay, x))
        dry_in, self.predelay = buf[:n], buf[n:]

        # Parallel damped feedback combs : y[t] = x[t] + g * lp(y[t - d])
        acc = np.zeros(n, dtype=np.float32)
        for i, hist in enumerate(self.combs):
            # hist holds the last d + 1 outputs ; damping = 2-tap low-pass
            past = (1 - self.DAMP) * hist[1 : n + 1] + self.DAMP * hist[:n]
            y = self.INPUT_GAIN * dry_in + self.FEEDBACK * past
            self.combs[i] = np.concatenate((hist[n:], y))
            acc += y

        # Series allpasses : y[t] = -g x[t] + x[t - d] + g y[t - d]
        g = self.ALLPASS_GAIN
        for i in range(len(self.ALLPASSES)):
            xin, yout = self.ap_in[i], self.ap_out[i]
            y = -g * acc + xin[:n] + g * yout[:n]
            self.ap_in[i] = np.concatenate((xin[n:], acc))
            self.ap_out[i] = np.concatenate((yout[n:], y))
            acc = y

        return self.DRY * x + self.WET * acc


class BitCrush:
    """Retro 8-bit console voice: few bits and a low sample rate."""

    def __init__(self, bits: int = 5, hold: int = 6) -> None:
        """Quantize to ``bits`` and keep 1 sample out of ``hold``."""
        self.np = _numpy()
        self.levels = 2 ** (bits - 1)
        self.hold = hold
        self.band = FIR(150, 7000)

    def process(self, x: 'np.ndarray') -> 'np.ndarray':
        """Apply the effect to one block."""
        np = self.np
        # Boost first so a normal voice uses the few levels available
        y = np.tanh(3 * self.band.process(x))
        y = np.round(y * self.levels) / self.levels
        # Sample-and-hold : 48 kHz -> 8 kHz staircase (BLOCK % hold == 0)
        return 0.55 * np.repeat(y[:: self.hold], self.hold)[: len(x)]


class Megaphone:
    """Tight band-pass and hard distortion, like a bullhorn."""

    def __init__(self) -> None:
        """Build the pre- and post-distortion band-pass filters."""
        self.np = _numpy()
        self.pre = FIR(700, 2400, taps=257)
        self.post = FIR(500, 3500)

    def process(self, x: 'np.ndarray') -> 'np.ndarray':
        """Apply the effect to one block."""
        np = self.np
        y = np.tanh(25 * self.pre.process(x))
        return 0.3 * self.post.process(y)


def _alien() -> Chain:
    """Fast vibrato on a slightly raised voice."""
    return Chain(PitchShift(1.22), ModDelay(4, 0.8, 7.5, wet=1.0))


EFFECTS = {
    'robot': Robot,
    'deep': lambda: PitchShift(0.7),  # about -6 semitones
    'chipmunk': lambda: PitchShift(1.5),  # about +7 semitones
    'radio': Radio,
    'underwater': Underwater,
    'cathedral': Cathedral,
    '8bit': BitCrush,
    'megaphone': Megaphone,
    'alien': _alien,
}


# --------------------------------------------------------------------------
# Virtual mic + audio pipeline
# --------------------------------------------------------------------------


class VoiceChanger:
    """Create the virtual mic and stream the real mic through the effects."""

    def __init__(
        self,
        pulse: 'Pulse',
        effects: list[str],
        source: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Validate the setup; nothing is created before :meth:`start`.

        Args:
            pulse: pulsectl connection (only used from the main thread).
            effects: Effect names applied in order (see ``EFFECTS``).
            source: Real mic to capture; defaults to the current default
                source.
            logger: Logger to report to.
        """
        self.pulse = pulse
        self.logger = logger or logging.getLogger(__name__)
        self.np = _numpy()
        for tool in ('parec', 'pacat'):
            if shutil.which(tool) is None:
                msg = f"voice effects require '{tool}' (pulseaudio-utils)."
                raise RuntimeError(msg)
        unknown = [e for e in effects if e not in EFFECTS]
        if unknown:
            msg = f'Unknown voice effect(s) : {", ".join(unknown)}'
            raise ValueError(msg)
        self.effect_names = effects
        self.chain = Chain(*(EFFECTS[name]() for name in effects))
        self.released = threading.Event()
        self.source = source
        self.modules: list[int] = []
        self.previous_default: str | None = None
        self.procs: list[subprocess.Popen] = []
        self.thread: threading.Thread | None = None
        self.running = False
        self.source_name = SOURCE_NAME

    # Virtual devices

    def _unload_stale_modules(self) -> None:
        """Remove virtual devices left behind by a previous crashed run."""
        for module in self.pulse.module_list():
            if SINK_NAME in (module.argument or ''):
                self.pulse.module_unload(module.index)

    def _create_virtual_mic(self) -> None:
        self.modules.append(
            self.pulse.module_load(
                'module-null-sink',
                f'sink_name={SINK_NAME} rate={RATE} channels=1 '
                'channel_map=mono sink_properties='
                '"device.description=\'pulseToTalk voice output\'"',
            )
        )
        self.modules.append(
            self.pulse.module_load(
                'module-remap-source',
                f'master={SINK_NAME}.monitor source_name={SOURCE_NAME} '
                'channels=1 channel_map=mono source_properties='
                '"device.description=\'pulseToTalk virtual mic\'"',
            )
        )

    def start(self) -> None:
        """Create the virtual mic, make it the default and start streaming."""
        self._unload_stale_modules()
        default = self.pulse.server_info().default_source_name
        if self.source is None:
            self.source = default
        self.previous_default = default

        self._create_virtual_mic()
        self.pulse.default_set(self.pulse.get_source_by_name(SOURCE_NAME))

        common = [
            f'--rate={RATE}',
            '--channels=1',
            '--format=float32le',
            '--raw',
            f'--latency-msec={LATENCY_MSEC}',
            '--client-name=pulseToTalk',
        ]
        rec = subprocess.Popen(
            ['parec', f'--device={self.source}', '--stream-name=voice-in', *common],
            stdout=subprocess.PIPE,
            bufsize=0,
        )
        play = subprocess.Popen(
            ['pacat', f'--device={SINK_NAME}', '--stream-name=voice-out', *common],
            stdin=subprocess.PIPE,
            bufsize=0,
        )
        self.procs = [rec, play]
        # Pipes hold 64 KiB (~340 ms) by default: once filled (e.g. while
        # the virtual mic warms up) they would never drain and the delay
        # would stay forever. Shrink them and never block on the output.
        for pipe in (rec.stdout, play.stdin):
            with contextlib.suppress(OSError):
                fcntl.fcntl(pipe.fileno(), fcntl.F_SETPIPE_SZ, 4096)
        os.set_blocking(play.stdin.fileno(), False)
        self.running = True
        self.thread = threading.Thread(target=self._pump, daemon=True)
        self.thread.start()
        self.logger.critical(
            f"Voice effect(s) {', '.join(self.effect_names)} : "
            f"'{self.source}' -> virtual mic '{SOURCE_NAME}'"
        )

    def _pump(self) -> None:
        """Read the real mic, apply the effect chain, write the virtual mic.

        Latency is kept bounded: when audio piles up on the input, the oldest
        blocks are dropped, and a block is skipped rather than queued when
        the output is not ready.
        """
        np = self.np
        rec, play = self.procs
        in_fd, out_fd = rec.stdout.fileno(), play.stdin.fileno()
        nbytes = BLOCK * 4
        pending = bytearray()
        try:
            while self.running:
                chunk = os.read(in_fd, 65536)
                if not chunk:
                    break
                pending += chunk
                # Too late : keep only the most recent blocks
                excess = len(pending) // nbytes - MAX_QUEUED_BLOCKS
                if excess > 0:
                    del pending[: excess * nbytes]
                while len(pending) >= nbytes:
                    block = np.frombuffer(bytes(pending[:nbytes]), dtype='<f4')
                    del pending[:nbytes]
                    if self.released.is_set():
                        self.released.clear()
                        self.chain.on_release()
                    block = self.chain.process(block)
                    out = np.clip(block, -1, 1).astype('<f4').tobytes()
                    # Atomic (< PIPE_BUF) : written whole or not at all
                    with contextlib.suppress(BlockingIOError):
                        os.write(out_fd, out)
        except (BrokenPipeError, ValueError, OSError):
            pass
        if self.running:
            self.logger.error('Voice changer stream stopped unexpectedly')

    def release(self) -> None:
        """Signal the end of a transmission (push-to-talk key released).

        Thread-safe: the effects are notified from the audio thread.
        """
        self.released.set()

    def stop(self) -> None:
        """Stop streaming, restore the default source, remove virtual mic."""
        self.running = False
        for proc in self.procs:
            proc.terminate()
        for proc in self.procs:
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=1)
        if self.previous_default:
            with contextlib.suppress(Exception):
                self.pulse.default_set(
                    self.pulse.get_source_by_name(self.previous_default)
                )
        for index in reversed(self.modules):
            with contextlib.suppress(Exception):
                self.pulse.module_unload(index)
        self.modules = []
