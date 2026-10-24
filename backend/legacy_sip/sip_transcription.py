"""SIP -> G.711/RTP -> 16 kHz PCM -> realtime transcription proof of concept.

All SIP/RTP and HTTP listeners bind to loopback. This is not a SIP registrar.
No microphone, office device, or door hardware is accessed by this server.
"""
import argparse
import asyncio
from array import array
from collections import deque
import json
import math
import os
from pathlib import Path
import queue
import secrets
import signal
import time
import wave

from aiohttp import web
from security import private_write
from sip_runtime import SipRuntime
from transcription import LocalSink, ElevenStream


class Session:
    def __init__(self, server, call):
        self.server, self.call = server, call
        self.id = secrets.token_hex(8)
        self.audio = queue.Queue(maxsize=100)  # 2 seconds, including native clock thread.
        self.overflow = False
        self.samples = self.nonzero = self.power = self.chunks = 0
        self.created = time.monotonic()
        self.failure = None
        self.finished = False
        self.backend = server.backend_factory()
        self.writer = None
        self.callback_errors = 0
        call.sink = self.receive_pcm
        self.task = asyncio.create_task(self.run())

    def receive_pcm(self, pcm):
        # Runs on the PJSIP audio clock thread: no network, disk or awaiting here.
        if self.finished:
            return
        try:
            self.audio.put_nowait(pcm)
        except queue.Full:
            self.overflow = True

    async def send(self, pcm):
        values = array('h', pcm)
        self.samples += len(values)
        self.nonzero += sum(v != 0 for v in values)
        self.power += sum(v * v for v in values)
        self.chunks += 1
        if self.writer:
            self.writer.writeframesraw(pcm)
        await self.backend.send(pcm)

    async def run(self):
        pending = bytearray()
        try:
            self.call.accept(180)
            await self.backend.start()
            if self.call.ended.is_set():
                return
            if self.server.record:
                path = self.server.folder / (self.id + '.wav')
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                self.record_file = os.fdopen(fd, 'wb')
                self.writer = wave.open(self.record_file, 'wb')
                self.writer.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            self.call.accept()
            while True:
                if self.overflow:
                    raise RuntimeError('audio_queue_overflow')
                if self.backend.failure:
                    raise RuntimeError('transcriber_failed')
                if self.call.failure or (self.call.port and self.call.port.errors):
                    raise RuntimeError('sip_audio_failed')
                if time.monotonic() - self.created >= self.server.max_seconds:
                    self.call.stop()
                try:
                    while len(pending) < 3200:
                        pending.extend(self.audio.get_nowait())
                except queue.Empty:
                    pass
                if len(pending) >= 3200:
                    await self.send(bytes(pending[:3200]))
                    del pending[:3200]
                elif self.call.ended.is_set() and self.audio.empty():
                    if pending:
                        await self.send(bytes(pending))
                    break
                else:
                    await asyncio.sleep(.01)
            await self.backend.finish()
            self.failure = self.backend.failure
        except asyncio.CancelledError:
            self.failure = 'server_stopped'
            raise
        except Exception as exc:
            # Fixed labels only: provider/network exceptions may contain secrets.
            self.failure = 'audio_queue_overflow' if self.overflow else 'call_processing_failed'
            self.error_type = type(exc).__name__
        finally:
            self.finished = True
            if self.call.port:
                self.callback_errors = self.call.port.errors
                self.call.port.enabled = False
            self.call.stop()
            await self.backend.close()
            if self.writer:
                self.writer.close()
                self.record_file.close()
            self.server.completed.append(self.status())
            if self.server.active is self:
                self.server.active = None

    def status(self):
        return {'id': self.id, 'sip_state': self.call.state,
                'finished': self.finished, 'failure': self.failure,
                'samples': self.samples, 'audio_seconds': round(self.samples / 16000, 3),
                'nonzero_samples': self.nonzero,
                'rms': round(math.sqrt(self.power / self.samples), 2) if self.samples else 0,
                'chunks': self.chunks, 'callback_errors': self.callback_errors,
                'transcriber_sent_samples': self.backend.sent_samples,
                'transcript_events': list(self.backend.events),
                'recording': self.id + '.wav' if self.writer else None}


class Server:
    def __init__(self, folder, backend='local', key=None, fixture_url=None,
                 max_seconds=120, record=False, sip_port=0):
        self.folder = Path(folder)
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.folder.chmod(0o700)
        self.backend = backend
        if backend == 'local':
            self.backend_factory = LocalSink
        elif backend == 'fixture':
            if not fixture_url:
                raise ValueError('Fixture URL required')
            self.backend_factory = lambda: ElevenStream(fixture_url=fixture_url)
        elif backend == 'elevenlabs':
            if not key:
                raise ValueError('An ElevenLabs API key is required')
            self.backend_factory = lambda: ElevenStream(key=key)
        else:
            raise ValueError('Unknown backend')
        self.backend_factory()  # Validate configuration before opening any listeners.
        self.max_seconds, self.record = max_seconds, record
        self.token = secrets.token_urlsafe(32)
        self.active = None
        self.completed = deque(maxlen=20)
        self.sessions = set()
        self.runtime = SipRuntime(self.token, port=sip_port, incoming=self.incoming)
        self.http = None

    def incoming(self, call):
        # Includes the short final-transcript flush after a disconnected call.
        if self.active:
            self.runtime.rejected += 1
            call.accept(486)
            return
        session = self.active = Session(self, call)
        self.sessions.add(session.task)
        session.task.add_done_callback(self.sessions.discard)

    def status(self):
        return {'mode': 'loopback_sip_lab', 'backend': self.backend,
                'sip_port': self.runtime.port, 'rejected_calls': self.runtime.rejected,
                'active': self.active.status() if self.active else None,
                'completed': list(self.completed), 'microphone_open': False,
                'physical_door_connected': False}

    async def start(self):
        @web.middleware
        async def auth(request, handler):
            value = request.headers.get('Authorization', '')
            if not secrets.compare_digest(value, 'Bearer ' + self.token):
                raise web.HTTPUnauthorized()
            return await handler(request)

        async def status(request):
            return web.json_response(self.status())

        async def hangup(request):
            data = await request.json()
            if not self.active or data != {'call_id': self.active.id}:
                return web.json_response({'error': 'active_call_id_required'}, status=409)
            self.active.call.stop()
            return web.json_response({'hangup_requested': True})

        app = web.Application(middlewares=[auth], client_max_size=1024)
        app.router.add_get('/status', status)
        app.router.add_post('/hangup', hangup)
        self.http = web.AppRunner(app, access_log=None)
        await self.http.setup()
        site = web.TCPSite(self.http, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        private_write(self.folder / 'connection.json', json.dumps({
            'sip_port': self.runtime.port, 'token': self.token,
            'url': f'http://127.0.0.1:{port}', 'mode': 'loopback_sip_lab'}))

    async def close(self):
        if self.active:
            self.active.call.stop()
        if self.sessions:
            _, pending = await asyncio.wait(self.sessions, timeout=6)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        private_write(self.folder / 'last-run.json', json.dumps(self.status(), indent=2))
        (self.folder / 'connection.json').unlink(missing_ok=True)
        if self.http:
            await self.http.cleanup()
        await self.runtime.close()


async def serve(args):
    key = None
    if args.backend == 'elevenlabs':
        if args.api_key_file:
            path = Path(args.api_key_file)
            if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
                raise ValueError('API key file must be a regular private (0600) file')
            key = path.read_text().strip()
        else:
            key = os.environ.get('ELEVENLABS_API_KEY')
    server = Server(args.state, args.backend, key, args.fixture_url,
                    args.call_seconds, args.record, args.sip_port)
    try:
        await server.start()
        print('SIP transcription server ready (' + args.backend + '). Private connection file: ' +
              str((server.folder / 'connection.json').resolve()), flush=True)
        done = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig, done.set)
        try:
            await asyncio.wait_for(done.wait(), args.minutes * 60)
        except asyncio.TimeoutError:
            pass
    finally:
        await server.close()


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state', default='.state-sip-server')
    p.add_argument('--backend', choices=('local', 'fixture', 'elevenlabs'), default='local')
    p.add_argument('--api-key-file')
    p.add_argument('--fixture-url', help='Explicit local test fixture; never receives an API key')
    p.add_argument('--record', action='store_true', help='Opt in to private diagnostic WAV files')
    p.add_argument('--sip-port', type=int, default=0)
    p.add_argument('--call-seconds', type=float, default=120)
    p.add_argument('--minutes', type=float, default=10)
    return p


if __name__ == '__main__':
    p = parser()
    args = p.parse_args()
    if not 1 <= args.call_seconds <= 600 or not 0 < args.minutes <= 60:
        p.error('Use 1–600 seconds per call and at most 60 minutes per run')
    if args.sip_port and not 1024 <= args.sip_port <= 65535:
        p.error('SIP port must be zero (automatic) or above 1023')
    if args.backend != 'fixture' and args.fixture_url:
        p.error('--fixture-url requires --backend fixture')
    asyncio.run(serve(args))
