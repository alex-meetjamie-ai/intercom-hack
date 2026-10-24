"""Bounded mono PCM audio with opt-in diagnostic recordings.

The device backend is imported lazily. Constructing/listing devices does not
open streams. Only an explicit MacAudio.start() opens the selected devices.
"""
import argparse
import asyncio
import json
import math
import threading
import time
from array import array
from fractions import Fraction
from aiortc import AudioStreamTrack
from av import AudioFrame

RATE = 48000
SAMPLES = 960
FRAME_BYTES = SAMPLES * 2
SILENCE = bytes(FRAME_BYTES)


class PcmPipe:
    """At most 200 ms of s16 mono audio; late audio is discarded, never replayed."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.data = bytearray()
        self.updated = 0.0
        self.enabled = False
        self.dropped_bytes = self.underruns = 0
        self.capacity = RATE * 2 // 5

    def enable(self, value):
        with self.lock:
            self.enabled = bool(value)
            self.data.clear()

    def push(self, pcm):
        if len(pcm) % 2 or len(pcm) > self.capacity:
            raise ValueError('Expected at most 200 ms of s16 mono PCM')
        if not self.lock.acquire(blocking=False):
            return
        try:
            if not self.enabled:
                return
            now = self.clock()
            if now - self.updated > .25:
                self.data.clear()
            excess = max(0, len(self.data) + len(pcm) - self.capacity)
            if excess:
                del self.data[:excess]
                self.dropped_bytes += excess
            self.data.extend(pcm)
            self.updated = now
        finally:
            self.lock.release()

    def read(self, size):
        if not 0 < size <= self.capacity or size % 2:
            raise ValueError('Invalid PCM read size')
        if not self.lock.acquire(blocking=False):
            return bytes(size)
        try:
            if not self.enabled or self.clock() - self.updated > .25:
                self.data.clear()
            available = min(size, len(self.data))
            result = bytes(self.data[:available])
            del self.data[:available]
            if available < size:
                self.underruns += 1
            return result + bytes(size - available)
        finally:
            self.lock.release()


class ToneAudio:
    source = 'generated_tone'

    def __init__(self):
        self.active = False
        self.samples = self.received_samples = 0
        self.playback_route = None

    def start(self):
        pass

    def set_active(self, active):
        if bool(active) != self.active:
            self.playback_route = None
        self.active = bool(active)

    def read_pcm(self, consumer='ems'):
        if not self.active:
            return SILENCE
        pcm = array('h', (int(3000 * math.sin(2 * math.pi * 440 * (self.samples + i) / RATE))
                          for i in range(SAMPLES))).tobytes()
        self.samples += SAMPLES
        return pcm

    def write_pcm(self, pcm, route='ems'):
        if self.active:
            self.playback_route = self.playback_route or route
            if route == self.playback_route:
                self.received_samples += len(pcm) // 2

    def status(self):
        return {'source': self.source, 'active': self.active, 'microphone_open': False,
                'received_samples': self.received_samples, 'recording': False}

    def close(self):
        self.set_active(False)


class MacAudio:
    source = 'mac_microphone'

    def __init__(self, input_device, output_device, output_gain=.35, backend=None):
        if (type(input_device) is not int or input_device < 0 or
                type(output_device) is not int or output_device < 0):
            raise ValueError('Select explicit numeric input and headphone output IDs')
        if not 0 <= output_gain <= 1:
            raise ValueError('Output gain must be between 0 and 1')
        self.input_device, self.output_device = input_device, output_device
        self.output_gain, self.backend = output_gain, backend
        self.capture, self.webrtc_capture, self.playback = PcmPipe(), PcmPipe(), PcmPipe()
        self.streams = []
        self.playback_route = None
        self.active = self.opened = self.faulted = False
        self.recorder = None
        self.capture_samples = self.played_samples = self.callback_errors = 0

    def start(self):
        if self.opened:
            raise RuntimeError('Audio devices already open')
        if self.backend is None:
            import sounddevice
            self.backend = sounddevice
        sd = self.backend
        sd.check_input_settings(device=self.input_device, channels=1, dtype='int16', samplerate=RATE)
        sd.check_output_settings(device=self.output_device, channels=1, dtype='int16', samplerate=RATE)
        try:
            # Separate streams allow a built-in microphone and USB headphones.
            self.streams.append(sd.RawOutputStream(device=self.output_device, samplerate=RATE,
                                channels=1, dtype='int16', blocksize=SAMPLES, callback=self._output))
            self.streams.append(sd.RawInputStream(device=self.input_device, samplerate=RATE,
                                channels=1, dtype='int16', blocksize=SAMPLES, callback=self._input))
            for stream in self.streams:
                stream.start()
            self.opened = True
        except BaseException:
            self.close()
            raise

    def set_active(self, active):
        if active and (not self.opened or self.faulted):
            raise RuntimeError('Audio devices are not available')
        if bool(active) == self.active:
            return
        self.active = bool(active)
        self.playback_route = None
        self.capture.enable(self.active)
        self.webrtc_capture.enable(self.active)
        self.playback.enable(self.active)

    def _input(self, data, frames, timing, status):
        if status:
            self.callback_errors += 1
        recorder = self.recorder
        if recorder and frames == SAMPLES:
            recorder.add('microphone', bytes(data))
        if self.active and frames == SAMPLES:
            self.capture.push(bytes(data))
            self.webrtc_capture.push(bytes(data))
            self.capture_samples += frames

    def _output(self, data, frames, timing, status):
        data[:] = bytes(len(data))
        if status:
            self.callback_errors += 1
        if self.active and frames == SAMPLES:
            data[:] = self.playback.read(frames * 2)
            self.played_samples += frames

    def read_pcm(self, consumer='ems'):
        if self.opened and not all(stream.active for stream in self.streams):
            self.faulted = True
            self.set_active(False)
            raise RuntimeError('Audio device stopped; end this test before reconnecting')
        if consumer not in ('ems', 'webrtc'):
            raise ValueError('Unknown audio consumer')
        return (self.webrtc_capture if consumer == 'webrtc' else self.capture).read(FRAME_BYTES)

    def write_pcm(self, pcm, route='ems'):
        # Decoded PCM, not a direct connection from a socket to an audio device.
        if self.active:
            self.playback_route = self.playback_route or route
            if self.playback_route != route:
                return
            scaled = array('h', (round(v * self.output_gain) for v in array('h', pcm)))
            self.playback.push(scaled.tobytes())

    def record_incoming(self, pcm, route):
        recorder = self.recorder
        if recorder:
            recorder.add('incoming_' + route, pcm)

    async def record(self, seconds, folder):
        from audio_recording import DiagnosticRecording
        if self.recorder or not self.opened:
            raise ValueError('Recording already active or microphone not open')
        recorder = self.recorder = DiagnosticRecording(seconds)
        try:
            await asyncio.sleep(seconds)
        finally:
            self.recorder = None
        return await asyncio.to_thread(recorder.finish, folder)

    def status(self):
        return {'source': self.source, 'active': self.active, 'microphone_open': self.opened,
                'input_device': self.input_device, 'output_device': self.output_device,
                'output_gain': self.output_gain, 'capture_samples': self.capture_samples,
                'played_samples': self.played_samples, 'callback_errors': self.callback_errors,
                'capture_dropped_bytes': self.capture.dropped_bytes,
                'playback_dropped_bytes': self.playback.dropped_bytes,
                'playback_route': self.playback_route,
                'faulted': self.faulted, 'recording': self.recorder is not None}

    def close(self):
        self.set_active(False)
        failed = []
        for stream in reversed(self.streams):
            try:
                stream.abort()
            except Exception:
                self.callback_errors += 1
            try:
                stream.close()
            except Exception:
                failed.append(stream)
        self.streams = failed
        self.opened = bool(failed)
        if failed:
            self.faulted = True
            raise RuntimeError('An audio device failed to close')


class BridgeAudioTrack(AudioStreamTrack):
    """Same PCM source for native WebRTC receivers, with its own bounded queue."""
    def __init__(self, audio):
        super().__init__()
        self.audio, self.samples, self.started = audio, 0, None

    async def recv(self):
        if self.started is None:
            self.started = time.monotonic()
        await asyncio.sleep(max(0, self.started + self.samples / RATE - time.monotonic()))
        frame = AudioFrame(format='s16', layout='mono', samples=SAMPLES)
        frame.planes[0].update(self.audio.read_pcm('webrtc'))
        frame.sample_rate, frame.pts, frame.time_base = RATE, self.samples, Fraction(1, RATE)
        self.samples += SAMPLES
        return frame


def devices():
    import sounddevice
    return [{'id': i, 'name': d['name'], 'inputs': d['max_input_channels'],
             'outputs': d['max_output_channels'], 'default_rate': d['default_samplerate']}
            for i, d in enumerate(sounddevice.query_devices())]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='List audio devices without capturing or playing audio')
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args()
    if args.list:
        print(json.dumps(devices(), indent=2))
    else:
        parser.print_help()
