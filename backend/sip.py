"""Small SIP-over-WebSocket endpoint for one local browser call.

Handles INVITE/ACK/BYE/CANCEL/OPTIONS with WebRTC SDP/media. It is deliberately
not a registrar, proxy or general PBX. The original UDP SIP lab lives in legacy_sip.
"""
import asyncio
from collections import deque
from dataclasses import dataclass
import re
import secrets

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration
from aiortc.mediastreams import MediaStreamError
from av import AudioResampler

from door import Visitor
from eleven import AgentError, ElevenAgent
from media import AgentAudio


@dataclass
class Message:
    first: str
    headers: dict
    body: str

    @classmethod
    def parse(cls, text):
        if len(text) > 131072 or '\r\n\r\n' not in text:
            raise ValueError('Malformed SIP message')
        head, body = text.split('\r\n\r\n', 1)
        lines = head.split('\r\n')
        headers = {}
        for line in lines[1:]:
            key, value = line.split(':', 1)
            key = key.strip().lower()
            headers.setdefault(key, []).append(value.strip())
        for key in ('from', 'to', 'call-id', 'cseq', 'content-length'):
            if len(headers.get(key, [])) != 1:
                raise ValueError('Missing/duplicate SIP header')
        if not headers.get('via') or len(body.encode()) != int(headers['content-length'][0]):
            raise ValueError('SIP length mismatch')
        return cls(lines[0], headers, body)

    def get(self, key):
        return self.headers[key][0]

    @property
    def method(self):
        return self.first.split()[0]

    def response(self, code, reason, tag=None, body='', contact=None):
        lines = [f'SIP/2.0 {code} {reason}']
        lines += ['Via: ' + value for value in self.headers['via']]
        to = self.get('to')
        if tag and ';tag=' not in to:
            to += ';tag=' + tag
        lines += ['From: ' + self.get('from'), 'To: ' + to,
                  'Call-ID: ' + self.get('call-id'), 'CSeq: ' + self.get('cseq')]
        if contact:
            lines.append('Contact: <' + contact + '>')
        if body:
            lines.append('Content-Type: application/sdp')
        lines.append('Content-Length: ' + str(len(body.encode())))
        return '\r\n'.join(lines) + '\r\n\r\n' + body


class Call:
    def __init__(self, app, ws, invite):
        self.app, self.ws, self.invite = app, ws, invite
        self.id = invite.get('call-id')
        self.tag = secrets.token_hex(10)
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.output = AgentAudio()
        self.visitor = Visitor(app.door, app.elevator, app.action, app.approvals,
                               recent_calls=app.recent_calls.snapshot())
        self.messages = deque(maxlen=30)
        self.agent = app.agent_factory(self.visitor, self.output, self.transcript)
        self.tasks = set()
        self.closing = False
        self.answered = False
        self.acked = asyncio.Event()
        self.invite_response = None
        self.cseq = 1
        self.pc.addTrack(self.output)

        @self.pc.on('track')
        def on_track(track):
            if track.kind == 'audio':
                self.spawn(self.forward_audio(track))

        @self.pc.on('connectionstatechange')
        async def connection_state():
            if self.pc.connectionState == 'connected':
                self.app.phase = 'connected'
            elif self.pc.connectionState in ('failed', 'closed') and not self.closing:
                await self.close(send_bye=True)

    def transcript(self, who, text):
        self.messages.append({'speaker': who, 'text': text})
        self.app.transcript(who, text)

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def establish(self):
        try:
            await self.ws.send_str(self.invite.response(180, 'Ringing', self.tag))
            await self.pc.setRemoteDescription(RTCSessionDescription(self.invite.body, 'offer'))
            await self.agent.start()
            if self.closing:
                return
            answer = await self.pc.createAnswer()
            await self.pc.setLocalDescription(answer)
            self.invite_response = self.invite.response(200, 'OK', self.tag,
                                self.pc.localDescription.sdp, self.app.contact)
            self.answered = True
            await self.ws.send_str(self.invite_response)
            self.spawn(self.watch())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.app.error = str(exc) if isinstance(exc, AgentError) else 'Could not establish the audio call.'
            if not self.closing:
                await self.ws.send_str(self.invite.response(503, 'Service Unavailable', self.tag))
                await self.close()

    async def forward_audio(self, track):
        resampler = AudioResampler(format='s16', layout='mono', rate=16000)
        try:
            await self.agent.ready.wait()
            while not self.closing:
                frame = await track.recv()
                for mono in resampler.resample(frame):
                    pcm = bytes(mono.planes[0])[:mono.samples * 2]
                    await self.agent.send(pcm)
        except (MediaStreamError, asyncio.CancelledError):
            pass
        except Exception:
            if not self.closing:
                self.app.error = 'The agent audio connection stopped.'
                await self.close(send_bye=True)

    async def watch(self):
        signals = []
        try:
            await asyncio.wait_for(self.acked.wait(), 10)
            signals = [asyncio.create_task(self.agent.closed.wait()),
                       asyncio.create_task(self.visitor.admission.wait()),
                       asyncio.create_task(self.agent.finished.wait())]
            done, _ = await asyncio.wait(signals, timeout=180, return_when=asyncio.FIRST_COMPLETED)
            if self.visitor.admission.is_set() and not self.closing:
                # Dispatch locally before BYE: no extra model turn or farewell.
                await self.visitor.tool('auto-elevator-' + self.id, 'send_elevator', {'floor': '0'})
            elif self.agent.finished.is_set():
                pass  # A refused/expired admission is a normal completed call.
            elif done and not self.closing:
                self.app.error = self.agent.error or 'The conversation ended.'
        except asyncio.TimeoutError:
            if not self.acked.is_set():
                self.app.error = 'The browser did not complete the call.'
        finally:
            for signal in signals:
                signal.cancel()
            await asyncio.gather(*signals, return_exceptions=True)
            await self.close(send_bye=True)

    async def bye(self):
        # Reverse the established dialog's From/To identities.
        contact = self.invite.headers.get('contact', [self.invite.get('from')])[0]
        match = re.search(r'<([^>]+)>', contact)
        target = match.group(1) if match else contact.split(';')[0]
        lines = [f'BYE {target} SIP/2.0',
                 f'Via: SIP/2.0/WS {self.app.host};branch=z9hG4bK{secrets.token_hex(10)}',
                 'Max-Forwards: 70',
                 'From: ' + self.invite.get('to') + ';tag=' + self.tag,
                 'To: ' + self.invite.get('from'), 'Call-ID: ' + self.id,
                 f'CSeq: {self.cseq} BYE', 'Content-Length: 0']
        await self.ws.send_str('\r\n'.join(lines) + '\r\n\r\n')

    async def close(self, send_bye=False):
        if self.closing:
            return
        self.closing = True
        self.visitor.close()
        if send_bye and self.answered and not self.ws.closed:
            try:
                await self.bye()
            except Exception:
                pass
        current = asyncio.current_task()
        tasks = [t for t in self.tasks if t is not current]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.agent.close()
        self.app.recent_calls.remember(self.visitor, self.messages)
        self.output.stop()
        await self.pc.close()
        if self.app.call is self:
            self.app.last_audio = {'sent_samples': self.agent.input_samples,
                                   'received_samples': self.output.received_samples}
            self.app.call = None
            self.app.phase = 'idle'


async def handle(app, ws, message):
    if message.first.startswith('SIP/2.0'):
        return  # Response to our BYE; transport is reliable WebSocket.
    method = message.method
    if message.get('cseq').split()[-1] != method:
        await ws.send_str(message.response(400, 'Bad Request'))
        return
    call = app.call
    matches = call and call.ws is ws and call.id == message.get('call-id')
    if method == 'OPTIONS':
        await ws.send_str(message.response(200, 'OK'))
    elif method == 'INVITE':
        if call:
            if matches and call.invite_response:
                await ws.send_str(call.invite_response)
            else:
                await ws.send_str(message.response(486, 'Busy Here'))
            return
        if (not message.first.startswith('INVITE sip:jamie@') or
                message.headers.get('content-type') != ['application/sdp']):
            await ws.send_str(message.response(488, 'Not Acceptable Here'))
            return
        app.error = None
        app.messages.clear()
        app.actions.clear()
        app.door.close()
        app.phase = 'ringing'
        app.call = call = Call(app, ws, message)
        await ws.send_str(message.response(100, 'Trying'))
        call.spawn(call.establish())
    elif method == 'ACK':
        if matches:
            call.acked.set()
    elif method == 'BYE':
        await ws.send_str(message.response(200 if matches else 481, 'OK' if matches else 'Call Does Not Exist'))
        if matches:
            await call.close()
    elif method == 'CANCEL':
        if matches and not call.answered:
            await ws.send_str(message.response(200, 'OK'))
            await ws.send_str(call.invite.response(487, 'Request Terminated', call.tag))
            await call.close()
        else:
            await ws.send_str(message.response(481, 'Call Does Not Exist'))
    else:
        await ws.send_str(message.response(405, 'Method Not Allowed'))
