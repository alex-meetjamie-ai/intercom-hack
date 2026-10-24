"""20 ms PCM playout and WebRTC conversion; no OS microphone or speakers."""
import asyncio
from fractions import Fraction
import time

from aiortc import AudioStreamTrack
from av import AudioFrame


class AgentAudio(AudioStreamTrack):
    def __init__(self):
        super().__init__()
        self.buffer = bytearray()
        self.samples = 0
        self.started = None
        self.received_samples = 0

    def push(self, pcm):
        if len(pcm) % 2:
            raise ValueError('Invalid PCM sample')
        if len(self.buffer) + len(pcm) > 16000 * 2 * 30:
            raise RuntimeError('Agent audio buffer overflow')
        self.buffer.extend(pcm)
        self.received_samples += len(pcm) // 2

    def interrupt(self):
        self.buffer.clear()

    async def drain(self):
        while self.buffer:
            await asyncio.sleep(.02)
        # Let the final RTP packets reach the caller before unlocking/hangup.
        await asyncio.sleep(.2)

    async def recv(self):
        if self.started is None:
            self.started = time.monotonic()
        await asyncio.sleep(max(0, self.started + self.samples / 16000 - time.monotonic()))
        pcm = bytes(self.buffer[:640])
        del self.buffer[:640]
        frame = AudioFrame(format='s16', layout='mono', samples=320)
        frame.planes[0].update(pcm.ljust(640, b'\0'))
        frame.sample_rate, frame.pts, frame.time_base = 16000, self.samples, Fraction(1, 16000)
        self.samples += 320
        return frame
