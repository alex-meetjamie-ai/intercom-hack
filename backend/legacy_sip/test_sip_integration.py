"""Real separate-process PJSIP calls and a local ElevenLabs protocol fixture.

No controller, external STT, microphone or physical relay is used. The fixture's
text is explicitly synthetic: these tests do not test speech recognition.
"""
import asyncio
from array import array
import base64
import json
import math
from pathlib import Path
import secrets
import signal
import sys
import tempfile
import unittest
import wave

from aiohttp import ClientSession, ClientTimeout, web

ROOT = Path(__file__).resolve().parent


class SipIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sip-integration-')
        self.root = Path(self.temp.name)
        self.processes, self.logs = [], []
        self.fixture_mode = 'normal'
        self.streams = []
        app = web.Application()
        app.router.add_get('/realtime', self.fixture)
        self.fixture_runner = web.AppRunner(app, access_log=None)
        await self.fixture_runner.setup()
        site = web.TCPSite(self.fixture_runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.fixture_url = f'ws://127.0.0.1:{port}/realtime'
        self.http = ClientSession(timeout=ClientTimeout(total=5), trust_env=False)

    async def asyncTearDown(self):
        failures = []
        for process, logfile in reversed(self.processes):
            if process.returncode is None:
                process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), 12)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                failures.append('process failed to shut down')
            if process.returncode != 0:
                failures.append(logfile.read_text()[-4000:])
        for log in self.logs:
            log.close()
        await self.http.close()
        await self.fixture_runner.cleanup()
        self.temp.cleanup()
        self.assertFalse(failures, '\n'.join(failures))

    async def fixture(self, request):
        self.assertNotIn('xi-api-key', request.headers)
        self.assertEqual(request.query['model_id'], 'scribe_v2_realtime')
        self.assertEqual(request.query['audio_format'], 'pcm_16000')
        self.assertEqual(request.query['commit_strategy'], 'vad')
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        stream = {'pcm': bytearray(), 'commits': 0, 'chunk_sizes': []}
        self.streams.append(stream)
        mode = self.fixture_mode
        if mode == 'reject':
            await ws.send_json({'message_type': 'auth_error', 'error': 'local test rejection'})
            await ws.close()
            return ws
        await ws.send_json({'message_type': 'session_started', 'session_id': 'local-fixture'})
        async for message in ws:
            if message.type != web.WSMsgType.TEXT:
                continue
            data = message.json()
            self.assertEqual(data['message_type'], 'input_audio_chunk')
            self.assertEqual(data['sample_rate'], 16000)
            pcm = base64.b64decode(data['audio_base_64'], validate=True)
            stream['pcm'].extend(pcm)
            if pcm:
                self.assertLessEqual(len(pcm), 6400)
                self.assertEqual(len(pcm) % 2, 0)
                stream['chunk_sizes'].append(len(pcm))
            if mode == 'drop' and len(stream['pcm']) >= 6400:
                await ws.close()
                break
            if mode == 'error' and len(stream['pcm']) >= 6400:
                await ws.send_json({'message_type': 'quota_exceeded', 'error': 'fixture'})
                await ws.close()
                break
            if len(stream['chunk_sizes']) == 5:
                await ws.send_json({'message_type': 'partial_transcript',
                                    'text': '[FIXTURE] audio arriving'})
            if data.get('commit'):
                stream['commits'] += 1
                if mode != 'no-final':
                    await ws.send_json({'message_type': 'committed_transcript',
                                        'text': '[FIXTURE] received test audio'})
        return ws

    async def spawn(self, script, state, *args):
        logfile = self.root / (state + '.log')
        log = logfile.open('wb')
        self.logs.append(log)
        process = await asyncio.create_subprocess_exec(sys.executable, str(ROOT / script),
            '--state', str(self.root / state), '--minutes', '2', *args,
            cwd=ROOT, stdout=log, stderr=log)
        self.processes.append((process, logfile))
        filename = 'connection.json' if script == 'sip_transcription.py' else 'reader/control.json'
        path = self.root / state / filename
        for _ in range(150):
            if path.exists():
                return json.loads(path.read_text())
            if process.returncode is not None:
                self.fail(logfile.read_text())
            await asyncio.sleep(.04)
        self.fail('Process never became ready: ' + logfile.read_text())

    async def start(self, seconds=30, wav=None, backend='fixture'):
        args = ['--backend', backend, '--record', '--call-seconds', str(seconds)]
        if backend == 'fixture':
            args += ['--fixture-url', self.fixture_url]
        self.server = await self.spawn('sip_transcription.py', 'server', *args)
        args = ['--server', str(self.root / 'server/connection.json')]
        if wav:
            args += ['--wav', str(wav)]
        self.reader = await self.spawn('sip_lab.py', 'reader', *args)

    async def request(self, connection, path, data=None, expected=200, authorized=True):
        headers = {'Authorization': 'Bearer ' + connection['token']} if authorized else {}
        method = self.http.get if data is None else self.http.post
        kwargs = {} if data is None else {'json': data}
        async with method(connection['url'] + path, headers=headers, **kwargs) as response:
            self.assertEqual(response.status, expected, await response.text())
            if expected == 401:
                return None
            return await response.json()

    async def ring(self, name):
        return await self.request(self.reader, '/sks-event', {'event': 'door-call', 'call_id': name})

    async def until(self, predicate, timeout=8):
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            status = await self.request(self.server, '/status')
            if predicate(status):
                return status
            await asyncio.sleep(.04)
        self.fail('Timed out: ' + repr(status))

    async def raw_invite(self, token):
        loop = asyncio.get_running_loop()
        result = loop.create_future()
        class Protocol(asyncio.DatagramProtocol):
            def datagram_received(self, data, addr):
                code = int(data.split(b' ', 2)[1])
                if code >= 200 and not result.done():
                    result.set_result(code)
        transport, _ = await loop.create_datagram_endpoint(Protocol, local_addr=('127.0.0.1', 0))
        port = transport.get_extra_info('sockname')[1]
        tag = secrets.token_hex(6)
        sdp = 'v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=lab\r\nc=IN IP4 127.0.0.1\r\nt=0 0\r\nm=audio 55000 RTP/AVP 0\r\na=rtpmap:0 PCMU/8000\r\n'
        packet = (f'INVITE sip:transcribe@127.0.0.1:{self.server["sip_port"]} SIP/2.0\r\n'
                  f'Via: SIP/2.0/UDP 127.0.0.1:{port};branch=z9hG4bK{tag}\r\n'
                  f'From: <sip:test@127.0.0.1>;tag={tag}\r\nTo: <sip:transcribe@127.0.0.1>\r\n'
                  f'Call-ID: {tag}@localhost\r\nCSeq: 1 INVITE\r\nMax-Forwards: 70\r\n'
                  f'Contact: <sip:test@127.0.0.1:{port}>\r\nX-Intercom-Lab-Key: {token}\r\n'
                  f'Content-Type: application/sdp\r\nContent-Length: {len(sdp)}\r\n\r\n{sdp}')
        try:
            transport.sendto(packet.encode(), ('127.0.0.1', self.server['sip_port']))
            return await asyncio.wait_for(result, 3)
        finally:
            transport.close()

    async def test_real_rtp_transcription_protocol_repeat_and_access_control(self):
        await self.start()
        await self.request(self.server, '/status', expected=401, authorized=False)
        await self.request(self.reader, '/sks-event', {'event': 'door-call', 'call_id': 'bad'},
                           expected=401, authorized=False)
        self.assertEqual(await self.raw_invite('invalid'), 403)
        await self.ring('one')
        active = await self.until(lambda s: s['active'] and s['active']['samples'] > 16000)
        self.assertEqual(active['active']['sip_state'], 'confirmed')
        self.assertEqual(await self.raw_invite(self.server['token']), 486)
        await self.request(self.server, '/hangup', {'call_id': 'stale'}, expected=409)
        await self.request(self.server, '/hangup', {'call_id': active['active']['id']})
        result = await self.until(lambda s: len(s['completed']) == 1)
        call = result['completed'][0]
        self.assertIsNone(call['failure'])
        self.assertEqual(call['callback_errors'], 0)
        self.assertGreater(call['rms'], 1800)
        self.assertLess(call['rms'], 2400)
        self.assertEqual(call['samples'], call['transcriber_sent_samples'])
        self.assertEqual(len(self.streams[0]['pcm']), call['samples'] * 2)
        self.assertEqual(self.streams[0]['commits'], 1)
        self.assertTrue(any(e['type'] == 'committed_transcript' for e in call['transcript_events']))
        pcm = array('h', self.streams[0]['pcm'])
        # Verify the RTP codec/resampling path preserved the actual source tone.
        segment = pcm[4000:12000]
        crossings = sum(a <= 0 < b for a, b in zip(segment, segment[1:]))
        self.assertAlmostEqual(crossings * 16000 / len(segment), 440, delta=4)
        with wave.open(str(self.root / 'server' / call['recording']), 'rb') as wav:
            self.assertEqual(wav.getframerate(), 16000)
            self.assertEqual(wav.readframes(wav.getnframes()), self.streams[0]['pcm'])
        await asyncio.sleep(.6)
        await self.ring('two')
        await self.until(lambda s: s['active'] and s['active']['samples'] > 4000)
        await self.request(self.reader, '/sks-event', {'event': 'visitor-left', 'call_id': 'two'})
        result = await self.until(lambda s: len(s['completed']) == 2)
        self.assertIsNone(result['completed'][1]['failure'])
        status = await self.request(self.reader, '/status')
        self.assertNotIn('confirmed', str(status))

    async def test_provider_failure_ends_call_and_next_call_recovers(self):
        await self.start()
        for index, mode in enumerate(('reject', 'drop', 'error', 'normal')):
            self.fixture_mode = mode
            await self.ring('failure-' + mode)
            if mode == 'normal':
                await self.until(lambda s: s['active'] and s['active']['samples'] > 8000)
                await self.request(self.reader, '/hangup', {})
            status = await self.until(lambda s: len(s['completed']) == index + 1)
            call = status['completed'][-1]
            if mode == 'normal':
                self.assertIsNone(call['failure'])
            else:
                self.assertIsNotNone(call['failure'])
            await asyncio.sleep(.7)

    async def test_server_call_limit_and_local_backend(self):
        await self.start(seconds=1, backend='local')
        await self.ring('timeout')
        status = await self.until(lambda s: len(s['completed']) == 1)
        call = status['completed'][0]
        self.assertIsNone(call['failure'])
        self.assertGreater(call['samples'], 8000)
        self.assertLess(call['audio_seconds'], 2)
        self.assertEqual(call['transcript_events'], [])
        self.assertEqual(self.streams, [])

    async def test_final_transcript_timeout_is_reported(self):
        self.fixture_mode = 'no-final'
        await self.start(seconds=1)
        await self.ring('no-final')
        status = await self.until(lambda s: len(s['completed']) == 1)
        self.assertEqual(status['completed'][0]['failure'], 'final_transcript_timeout')

    async def test_generated_speech_wav(self):
        wav = self.root / 'speech.wav'
        process = await asyncio.create_subprocess_exec('/usr/bin/say', '-v', 'Samantha',
            '-o', str(wav), '--file-format=WAVE', '--data-format=LEI16@48000',
            'Hello. This is a local intercom audio test. Please leave the door closed.',
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, errors = await process.communicate()
        self.assertEqual(process.returncode, 0, errors.decode())
        await self.start(seconds=6, wav=wav)
        await self.ring('speech')
        status = await self.until(lambda s: len(s['completed']) == 1, timeout=12)
        call = status['completed'][0]
        self.assertIsNone(call['failure'])
        self.assertGreater(call['rms'], 100)
        self.assertGreater(call['nonzero_samples'], 16000)
        self.assertIn('[FIXTURE]', call['transcript_events'][-1]['text'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
