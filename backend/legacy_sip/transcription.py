"""Bounded realtime PCM transcription transport. No SIP or audio devices here."""
import asyncio
import base64
from collections import deque
from urllib.parse import urlsplit

from aiohttp import ClientSession, ClientTimeout, WSMsgType

ELEVEN_URL = 'wss://api.elevenlabs.io/v1/speech-to-text/realtime'


class TranscriptionError(RuntimeError):
    pass


class LocalSink:
    """Offline audio consumption; deliberately produces no invented transcript."""
    def __init__(self):
        self.events = deque(maxlen=100)
        self.sent_samples = 0
        self.failure = None

    async def start(self):
        pass

    async def send(self, pcm):
        self.sent_samples += len(pcm) // 2

    async def finish(self):
        pass

    async def close(self):
        pass


class ElevenStream(LocalSink):
    """Same wire implementation for ElevenLabs and the explicit loopback fixture.

    Use VAD for live segment commits and an explicit final commit at hangup.
    No audio is retained here. Transcript history is bounded and in memory.
    """
    def __init__(self, key=None, fixture_url=None):
        super().__init__()
        if fixture_url:
            url = urlsplit(fixture_url)
            if (url.scheme != 'ws' or url.hostname != '127.0.0.1' or
                    not url.port or url.username or url.password or url.query or url.fragment):
                raise ValueError('Fixture must be a plain ws://127.0.0.1:PORT/path URL')
            if key:
                raise ValueError('Never send an API key to the fixture')
        elif not key:
            raise ValueError('ElevenLabs requires an API key')
        self.key, self.url = key, fixture_url or ELEVEN_URL
        self.session = self.ws = self.receiver = None
        self.finishing = False
        self.commit_count = 0

    async def start(self):
        self.session = ClientSession(timeout=ClientTimeout(total=10), trust_env=False)
        try:
            self.ws = await asyncio.wait_for(self.session.ws_connect(
                self.url, headers={'xi-api-key': self.key} if self.key else {},
                params={'model_id': 'scribe_v2_realtime', 'audio_format': 'pcm_16000',
                        'commit_strategy': 'vad', 'include_timestamps': 'false'},
                heartbeat=15, max_msg_size=65536), 10)
            initial = await asyncio.wait_for(self.ws.receive_json(), 5)
            if initial.get('message_type') != 'session_started':
                raise TranscriptionError('transcriber_session_rejected')
            self.receiver = asyncio.create_task(self._receive())
        except BaseException:
            await self.close()
            raise

    async def _receive(self):
        try:
            async for message in self.ws:
                if message.type != WSMsgType.TEXT:
                    if message.type == WSMsgType.ERROR:
                        raise TranscriptionError('transcriber_socket_error')
                    continue
                data = message.json()
                kind = data.get('message_type', '')
                if kind in ('partial_transcript', 'committed_transcript'):
                    value = data.get('text', '')
                    if not isinstance(value, str):
                        raise TranscriptionError('transcriber_invalid_response')
                    self.events.append({'type': kind, 'text': value[:8192]})
                    if kind == 'committed_transcript':
                        self.commit_count += 1
                elif kind == 'warning':
                    # Do not copy provider diagnostics, which may contain user data.
                    self.events.append({'type': 'provider_warning'})
                elif 'error' in data or kind.endswith('_error') or kind in ('error', 'auth_error', 'rate_limited',
                        'quota_exceeded', 'resource_exhausted', 'queue_overflow', 'input_error'):
                    raise TranscriptionError('transcriber_rejected_audio')
            if not self.finishing:
                raise TranscriptionError('transcriber_disconnected')
        except asyncio.CancelledError:
            raise
        except Exception:
            self.failure = 'transcriber_receive_failed'

    async def send(self, pcm):
        if self.failure or not self.ws or self.ws.closed:
            raise TranscriptionError(self.failure or 'transcriber_closed')
        if len(pcm) % 2 or not 0 < len(pcm) <= 6400:
            raise ValueError('Expected at most 200 ms of 16 kHz mono s16le PCM')
        await asyncio.wait_for(self.ws.send_json({
            'message_type': 'input_audio_chunk',
            'audio_base_64': base64.b64encode(pcm).decode('ascii'),
            'sample_rate': 16000, 'commit': False}), 3)
        self.sent_samples += len(pcm) // 2

    async def finish(self):
        if not self.sent_samples or self.failure:
            return
        # Allow a final committed transcript to arrive before closing the socket.
        previous = self.commit_count
        await asyncio.wait_for(self.ws.send_json({
            'message_type': 'input_audio_chunk', 'audio_base_64': '',
            'sample_rate': 16000, 'commit': True}), 3)
        deadline = asyncio.get_running_loop().time() + 4
        while self.commit_count == previous and not self.failure:
            if asyncio.get_running_loop().time() >= deadline:
                self.failure = 'final_transcript_timeout'
                break
            await asyncio.sleep(.02)

    async def close(self):
        self.finishing = True
        if self.receiver:
            self.receiver.cancel()
            await asyncio.gather(self.receiver, return_exceptions=True)
            self.receiver = None
        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()
        self.key = None
