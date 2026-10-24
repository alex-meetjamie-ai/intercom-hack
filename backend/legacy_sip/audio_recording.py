"""Explicit, time-limited diagnostic WAV recording; never enabled by default."""
import math
import os
import threading
import time
import uuid
import wave
from array import array
from pathlib import Path


class DiagnosticRecording:
    RATE = 48000
    SOURCES = ('microphone', 'incoming_ems', 'incoming_webrtc')

    def __init__(self, seconds, clock=time.monotonic):
        if type(seconds) is not int or not 1 <= seconds <= 30:
            raise ValueError('Recording duration must be 1..30 seconds')
        self.seconds, self.clock = seconds, clock
        self.deadline = clock() + seconds
        self.limit = seconds * self.RATE * 2
        self.buffers = {name: bytearray() for name in self.SOURCES}
        self.lock = threading.Lock()
        self.active = True

    def add(self, source, pcm):
        if source not in self.buffers or len(pcm) % 2:
            raise ValueError('Invalid recording source or PCM')
        with self.lock:
            if not self.active or self.clock() >= self.deadline:
                return
            target = self.buffers[source]
            target.extend(pcm[:max(0, self.limit - len(target))])

    def finish(self, folder):
        with self.lock:
            self.active = False
            buffers, self.buffers = self.buffers, {name: bytearray() for name in self.SOURCES}
        folder = Path(folder)
        if folder.is_symlink():
            raise ValueError('Recording folder cannot be a symlink')
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
        prefix = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
        results = {}
        for name, pcm in buffers.items():
            if not pcm:
                results[name] = {'path': None, 'samples': 0, 'note': 'No audio received in this window'}
                continue
            path = folder / f'{prefix}-{name}.wav'
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as file:
                with wave.open(file, 'wb') as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(self.RATE)
                    wav.writeframes(pcm)
            samples = array('h', pcm)
            results[name] = {'path': str(path.resolve()), 'samples': len(samples),
                             'audio_seconds': round(len(samples) / self.RATE, 3),
                             'peak': max(map(abs, samples)),
                             'rms': round(math.sqrt(sum(v*v for v in samples) / len(samples)), 1)}
        return {'window_seconds': self.seconds, 'recordings': results}
