"""Run the existing reader/SKS simulator with real loopback SIP/RTP calls."""
import argparse
import asyncio
import json
from pathlib import Path
import signal
import wave

from audio_io import ToneAudio, SILENCE, FRAME_BYTES
from security import private_write
from sip_calls import SipCalls
from sip_runtime import SipRuntime
from sks_lab import SksLab


class WavAudio(ToneAudio):
    source = 'local_wav'

    def __init__(self, path):
        super().__init__()
        with wave.open(str(path), 'rb') as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 48000):
                raise ValueError('WAV must be mono 48 kHz 16-bit PCM')
            if wav.getnframes() > 48000 * 60:
                raise ValueError('Use a WAV of at most 60 seconds')
            self.pcm = wav.readframes(wav.getnframes())
        if not self.pcm:
            raise ValueError('Empty WAV')
        self.position = 0

    def set_active(self, active):
        if active and not self.active:
            self.position = 0
        super().set_active(active)

    def read_pcm(self, consumer='ems'):
        if not self.active:
            return SILENCE
        data = self.pcm[self.position:self.position + FRAME_BYTES]
        self.position += len(data)
        self.samples += len(data) // 2
        return data.ljust(FRAME_BYTES, b'\0')


async def serve(args):
    path = Path(args.server)
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError('Connection file must be private (0600)')
    connection = json.loads(path.read_text())
    if connection.get('mode') != 'loopback_sip_lab':
        raise ValueError('Expected a local SIP server connection file')
    lab = SksLab(args.state, window=120)
    runtime = SipRuntime(connection['token'])
    lab.reader.calls = lab.calls = SipCalls(lab.reader, runtime, connection['sip_port'])
    if args.wav:
        lab.audio = WavAudio(args.wav)
        lab.bridge.audio = lab.reader.ems.audio = lab.audio
    try:
        await lab.start()
        print('Reader/SKS SIP lab ready. Private control file: ' +
              str((lab.reader.folder / 'control.json').resolve()), flush=True)
        done = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig, done.set)
        try:
            await asyncio.wait_for(done.wait(), args.minutes * 60)
        except asyncio.TimeoutError:
            pass
    finally:
        private_write(Path(args.state) / 'last-run.json', json.dumps({
            'calls': lab.calls.status(), 'bridge': lab.bridge.status()}))
        await lab.close()
        (lab.reader.folder / 'control.json').unlink(missing_ok=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--server', default='.state-sip-server/connection.json')
    p.add_argument('--state', default='.state-sip-reader')
    p.add_argument('--wav', help='Generated speech WAV; default is a generated 440 Hz tone')
    p.add_argument('--minutes', type=float, default=10)
    args = p.parse_args()
    if not 0 < args.minutes <= 60:
        p.error('Use at most 60 minutes per run')
    asyncio.run(serve(args))
