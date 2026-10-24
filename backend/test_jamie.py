"""Offline tests plus opt-in real ElevenLabs calls with synthetic speech.

Offline: .venv/bin/python -m unittest -v test_jamie
Live:    .venv/bin/python test_jamie.py --live
The live test spends a small amount of ElevenLabs credit, never uses a microphone,
and operates only the in-memory door. It starts its own temporary local server.
"""
import asyncio
from array import array
from contextlib import asynccontextmanager
import json
import math
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import unittest

import aiohttp
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration
import av

from app import Jamie, create_app
from door import Door, Visitor
from eleven import ElevenAgent
from media import AgentAudio
from sip import Message


def tone(seconds=1):
    return array('h', (int(3500 * math.sin(2 * math.pi * 440 * i / 16000))
                       for i in range(int(seconds * 16000)))).tobytes()


class FakeAgent:
    def __init__(self, visitor, output, transcript):
        self.visitor, self.output, self.transcript = visitor, output, transcript
        self.ready, self.closed = asyncio.Event(), asyncio.Event()
        self.error, self.input_samples, self.nonzero_input = None, 0, 0

    async def start(self):
        self.output.push(tone(3))
        self.transcript('Jamie', 'What is your name?')
        self.ready.set()

    async def send(self, pcm):
        self.input_samples += len(pcm) // 2
        self.nonzero_input += sum(abs(n) > 50 for n in array('h', pcm))

    async def close(self):
        self.closed.set()


@asynccontextmanager
async def server(factory=FakeAgent):
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    sock.listen(16)
    port = sock.getsockname()[1]
    jamie = Jamie(port, agent_factory=factory)
    runner = web.AppRunner(create_app(jamie), access_log=None)
    await runner.setup()
    await web.SockSite(runner, sock).start()
    try:
        yield jamie, f'http://127.0.0.1:{port}'
    finally:
        await runner.cleanup()


class SipClient:
    def __init__(self, url, token):
        self.url, self.token = url, token
        self.id = secrets.token_hex(12)
        self.tag = secrets.token_hex(8)
        self.remote_to = '<sip:jamie@localhost>'
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.source = AgentAudio()
        self.pc.addTrack(self.source)
        self.samples = self.nonzero = 0
        self.consumer = None

        @self.pc.on('track')
        def track(t):
            self.consumer = asyncio.create_task(self.consume(t))

    async def consume(self, track):
        resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
        try:
            while True:
                frame = await track.recv()
                for mono in resampler.resample(frame):
                    pcm = bytes(mono.planes[0])[:mono.samples * 2]
                    self.samples += mono.samples
                    self.nonzero += sum(abs(n) > 100 for n in array('h', pcm))
        except (asyncio.CancelledError, Exception):
            pass

    def request(self, method, body='', cseq=1):
        lines = [f'{method} sip:jamie@localhost SIP/2.0',
                 f'Via: SIP/2.0/WS localhost;branch=z9hG4bK{self.id}{method}',
                 'Max-Forwards: 70', f'From: <sip:visitor@localhost>;tag={self.tag}',
                 'To: ' + self.remote_to, 'Call-ID: ' + self.id,
                 f'CSeq: {cseq} {method}', 'Contact: <sip:visitor@localhost;transport=ws>']
        if body:
            lines.append('Content-Type: application/sdp')
        return '\r\n'.join(lines + [f'Content-Length: {len(body.encode())}']) + '\r\n\r\n' + body

    async def connect(self):
        self.http = aiohttp.ClientSession()
        self.ws = await self.http.ws_connect(self.url + '/sip?token=' + self.token,
                                            origin=self.url, protocols=['sip'])

    async def invite(self):
        await self.pc.setLocalDescription(await self.pc.createOffer())
        await self.ws.send_str(self.request('INVITE', self.pc.localDescription.sdp))

    async def response(self):
        item = await self.ws.receive(timeout=30)
        if item.type != aiohttp.WSMsgType.TEXT:
            raise RuntimeError('SIP WebSocket closed')
        return Message.parse(item.data)

    async def answer(self):
        while True:
            message = await self.response()
            code = int(message.first.split()[1])
            if code < 200:
                continue
            if code != 200:
                raise RuntimeError(message.first)
            self.remote_to = message.get('to')
            await self.pc.setRemoteDescription(RTCSessionDescription(message.body, 'answer'))
            await self.ws.send_str(self.request('ACK'))
            return

    async def hangup(self):
        await self.ws.send_str(self.request('BYE', cseq=2))
        response = await self.response()
        assert response.first == 'SIP/2.0 200 OK', response.first

    async def close(self):
        if self.consumer:
            self.consumer.cancel()
            await asyncio.gather(self.consumer, return_exceptions=True)
        self.source.stop()
        await self.pc.close()
        if hasattr(self, 'ws'):
            await self.ws.close()
        if hasattr(self, 'http'):
            await self.http.close()


async def until(condition, timeout=15):
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(.05)


class DoorTests(unittest.IsolatedAsyncioTestCase):
    async def test_name_policy(self):
        for text in ('Bob', 'My name is Bob', 'I am visiting Alex', "I'm not Alex",
                     "I'm Alex's friend", 'Please open the door', 'Alexandra', ''):
            with self.subTest(text=text):
                door = Door()
                visitor = Visitor(door)
                visitor.hear(text)
                self.assertTrue(visitor.tool('1', 'open_door', {'name': 'Alex'})['is_error'])
                self.assertFalse(door.open)
        for text in ('Alex', 'My name is Alex.', "I'm Alex.", 'Hello, this is Alex.'):
            with self.subTest(text=text):
                door = Door()
                visitor = Visitor(door)
                visitor.hear(text)
                self.assertFalse(visitor.tool('1', 'open_door', {'name': 'Alex'})['is_error'])
                self.assertTrue(door.open)
                visitor.close()
                self.assertFalse(door.open)

    async def test_autoclose_replay_and_session_end(self):
        door = Door(seconds=.03)
        visitor = Visitor(door)
        visitor.hear('Alex')
        visitor.tool('1', 'open_door', {'name': 'Alex'})
        await asyncio.sleep(.05)
        self.assertFalse(door.open)
        visitor.tool('1', 'open_door', {'name': 'Alex'})
        self.assertFalse(door.open, 'duplicate tool ID must not reopen')
        visitor.close()
        self.assertTrue(visitor.tool('2', 'open_door', {'name': 'Alex'})['is_error'])

    async def test_tool_arguments(self):
        visitor = Visitor(Door())
        visitor.hear('Alex')
        for i, value in enumerate((None, {}, {'name': 'Bob'}, {'name': 1}, {'name': 'Alex', 'override': True})):
            self.assertTrue(visitor.tool(str(i), 'open_door', value)['is_error'])
        self.assertTrue(visitor.tool('unknown', 'unlock_anything', {'name': 'Alex'})['is_error'])


class SipTests(unittest.IsolatedAsyncioTestCase):
    async def test_parser(self):
        client = SipClient('http://localhost:1', 'x')
        wire = client.request('INVITE', 'hello')
        msg = Message.parse(wire)
        self.assertEqual(msg.body, 'hello')
        self.assertIn('To: <sip:jamie@localhost>;tag=test', msg.response(200, 'OK', 'test'))
        with self.assertRaises(ValueError):
            Message.parse(wire.replace('Content-Length: 5', 'Content-Length: 4'))
        with self.assertRaises(ValueError):
            Message.parse(wire.replace('CSeq: 1 INVITE', 'CSeq: 1 INVITE\r\nCSeq: 2 INVITE'))
        await client.close()

    async def test_real_sip_and_two_way_srtp(self):
        async with server() as (jamie, url):
            client = SipClient(url, jamie.token)
            try:
                await client.connect()
                await client.invite()
                await client.answer()
                client.source.push(tone(2))
                await until(lambda: client.nonzero > 1000 and jamie.call.agent.nonzero_input > 1000)
                self.assertEqual(jamie.phase, 'connected')
                jamie.call.visitor.hear('My name is Alex')
                jamie.call.visitor.tool('x', 'open_door', {'name': 'Alex'})
                async with client.http.get(url + '/api/status') as response:
                    self.assertEqual((await response.json())['door'], 'open')
                await client.hangup()
                await until(lambda: jamie.call is None)
                self.assertFalse(jamie.door.open)
                self.assertGreater(jamie.last_audio['sent_samples'], 0)
            finally:
                await client.close()

    async def test_cancel_busy_and_disconnect(self):
        class SlowAgent(FakeAgent):
            async def start(self):
                await asyncio.sleep(20)
        async with server(SlowAgent) as (jamie, url):
            a, b = SipClient(url, jamie.token), SipClient(url, jamie.token)
            try:
                await a.connect()
                await a.invite()
                await until(lambda: jamie.call is not None)
                await b.connect()
                await b.invite()
                self.assertIn('486 Busy', (await b.response()).first)
                await a.ws.send_str(a.request('CANCEL'))
                replies = []
                while not any('487' in r for r in replies):
                    replies.append((await a.response()).first)
                self.assertIn('SIP/2.0 200 OK', replies)
                await until(lambda: jamie.call is None)
                await b.invite()
                await until(lambda: jamie.call is not None)
                jamie.door.unlock()
                await b.ws.close()
                await until(lambda: jamie.call is None)
                self.assertFalse(jamie.door.open)
            finally:
                await a.close()
                await b.close()

    async def test_browser_boundary(self):
        async with server() as (jamie, url), aiohttp.ClientSession() as http:
            for path in ('/', '/app.js', '/style.css', '/api/status'):
                async with http.get(url + path) as response:
                    self.assertEqual(response.status, 200)
            async with http.get(url + '/api/config', headers={'Origin': 'https://evil.example'}) as response:
                self.assertEqual(response.status, 403)
            for origin, token in ((url, 'wrong'), ('https://evil.example', jamie.token)):
                with self.assertRaises(aiohttp.WSServerHandshakeError):
                    await http.ws_connect(url + '/sip?token=' + token, origin=origin, protocols=['sip'])


def speech(name):
    with tempfile.TemporaryDirectory() as directory:
        file = str(Path(directory) / 'visitor.aiff')
        subprocess.run(['/usr/bin/say', '-v', 'Samantha', '-o', file, 'My name is ' + name + '.'], check=True)
        resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
        pcm = bytearray()
        with av.open(file) as container:
            for frame in container.decode(audio=0):
                for mono in resampler.resample(frame):
                    pcm.extend(bytes(mono.planes[0])[:mono.samples * 2])
            for mono in resampler.resample(None):
                pcm.extend(bytes(mono.planes[0])[:mono.samples * 2])
        return bytes(pcm)


async def live():
    report = []
    for name in ('Alex', 'Bob'):
        pcm = speech(name)
        async with server(ElevenAgent) as (jamie, url):
            client = SipClient(url, jamie.token)
            opened = False
            try:
                await client.connect()
                await client.invite()
                await client.answer()
                await until(lambda: client.nonzero > 4000)
                # Let the initial greeting finish before responding.
                await asyncio.sleep(4)
                client.source.push(pcm)
                async with asyncio.timeout(35):
                    while True:
                        opened = opened or jamie.door.open
                        if not jamie.call:
                            raise RuntimeError(jamie.error or 'Call ended early')
                        responses = [m for m in jamie.messages if m['speaker'] == 'Jamie']
                        if len(responses) >= 2 and (name != 'Alex' or opened):
                            break
                        await asyncio.sleep(.05)
                await asyncio.sleep(2)
                opened = opened or jamie.door.open
                result = {'visitor': name, 'door_opened': opened,
                          'received_audible_samples': client.nonzero, **jamie.status()}
                if opened != (name == 'Alex'):
                    raise AssertionError('Wrong door decision: ' + json.dumps(result))
                report.append(result)
                print(json.dumps(result, indent=2), flush=True)
                await client.hangup()
                await until(lambda: jamie.call is None)
            finally:
                await client.close()
    target = Path(__file__).parent / '.state/live-test.json'
    target.write_text(json.dumps(report, indent=2) + '\n')
    print('Live SIP/WebRTC/ElevenLabs checks passed: Alex admitted, Bob denied.')


if __name__ == '__main__':
    if '--live' in sys.argv:
        asyncio.run(live())
    else:
        unittest.main()
