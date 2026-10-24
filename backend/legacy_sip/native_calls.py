"""Access-style call request, WebSocket signalling and real WebRTC audio.

Experimental vendor interoperability. Defaults to a generated tone; an explicitly
configured bridge can supply PCM from selected audio devices.
"""
import asyncio
import contextlib
import json
import re
import ssl
import time
import uuid
from array import array
from urllib.parse import quote
from aiohttp import ClientSession, ClientTimeout, ClientWSTimeout, Fingerprint, TraceConfig, WSMsgType
from aiortc import RTCPeerConnection, RTCConfiguration, RTCIceServer, RTCSessionDescription, RTCRtpSender
from aiortc.sdp import candidate_from_sdp
from media_lab import Tone
from audio_io import BridgeAudioTrack
import av
from provisioning import scoped_url
from security import private_write


class CallError(Exception):
    pass


class NativeCalls:
    def __init__(self, reader):
        self.reader = reader
        self.http = None
        self.ws = None
        self.pc = None
        self.task = None
        self.media_tasks = []
        self.pending_ice = []
        self.room = None
        self.frames_received = 0
        self.audio_energy = 0
        self.state = 'idle'
        self.lock = asyncio.Lock()
        self.data_channel = None

    def status(self):
        audio = self.reader.ems.audio if getattr(self.reader, 'ems', None) else None
        return {'state': self.state, 'frames_received': self.frames_received,
                'received_nonzero_audio': bool(self.audio_energy),
                'source': audio.source if audio else 'generated tone',
                'legacy_webrtc_source': audio.source if audio else 'generated tone',
                'microphone_used': bool(audio and audio.status()['microphone_open']),
                'provisioned': bool(self.reader.state.get('provisioning'))}

    def provisioned(self):
        p = self.reader.state.get('provisioning', {})
        if not p.get('access_token') or not p.get('origin'):
            raise CallError('Call provisioning has not arrived')
        return p

    def trust(self):
        a = self.reader.state.get('adoption') or {}
        fp = a.get('extras', {}).get('http_cert_fingerprint', '').replace(':', '').lower()
        if fp:
            if not re.fullmatch(r'[0-9a-f]{64}', fp):
                raise CallError('HTTPS fingerprint must be SHA-256 for this prototype')
            return Fingerprint(bytes.fromhex(fp))
        if not a.get('broker_cert_ca'):
            raise CallError('No provisioned TLS trust anchor')
        ctx = ssl.create_default_context(cadata=a['broker_cert_ca'])
        ctx.check_hostname = False
        return ctx

    async def client(self):
        if self.http is None or self.http.closed:
            # ws_connect follows redirects internally. Stop them before another
            # destination is contacted, just as for the ordinary HTTP requests.
            trace = TraceConfig()
            async def reject_redirect(session, context, params):
                raise CallError('Controller redirects are not supported')
            trace.on_request_redirect.append(reject_redirect)
            self.http = ClientSession(timeout=ClientTimeout(total=12), trust_env=False, trace_configs=[trace])
        return self.http

    async def request(self, method, url, payload=None):
        p = self.provisioned()
        scoped_url(url, self.reader.controller, self.reader.lab)
        client = await self.client()
        async with client.request(method, url, json=payload, ssl=self.trust(),
                                  headers={'Authorization': 'Bearer ' + p['access_token']}, allow_redirects=False) as response:
            if response.status != 200:
                raise CallError(f'Controller HTTP status {response.status}')
            body = bytearray()
            async for chunk in response.content.iter_chunked(16384):
                body.extend(chunk)
                if len(body) > 1048576:
                    raise CallError('Controller response too large')
            result = json.loads(body)
            success = isinstance(result, dict) and (
                result.get('code', 0) in (0, 'SUCCESS') or
                (result.get('code') == 1 and result.get('codeS') == 'SUCCESS'))
            if not success:
                private_write(self.reader.folder / 'last-call-error.json', bytes(body))
                code = str(result.get('code', 'unknown')) if isinstance(result, dict) else 'invalid_json_shape'
                code = code if re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', code) else 'unknown'
                raise CallError(f'Controller rejected call operation ({code})')
            return result.get('data', result)

    async def ice_servers(self):
        endpoint = self.provisioned().get('endpoints', {}).get('ice_credentials')
        if not endpoint:
            self.reader.event('ice_host_candidates_only')
            return []
        result = await self.request('GET', endpoint)
        servers = []
        # First office test uses local host/relay paths only. Cloud TURN service
        # destinations are not inferred from an untested provisioning response.
        local = result.get('local') or {}
        for uri in local.get('uris', []):
            if not isinstance(uri, str):
                raise CallError('Invalid ICE service')
            match = re.fullmatch(r'(stun|turn|turns):([^:/?]+)(?::([0-9]+))?(?:\?transport=(udp|tcp))?', uri)
            if not match or match[2] != self.reader.controller:
                self.reader.event('ice_service_skipped', reason='outside_selected_controller')
                continue
            servers.append(RTCIceServer(urls=uri, username=local.get('username'), credential=local.get('password')))
        return servers

    async def ring(self):
        async with self.lock:
            if self.state != 'idle':
                raise CallError('A call is already active')
            p = self.provisioned()
            endpoint = p.get('endpoints', {}).get('remote_call')
            if not endpoint:
                raise CallError('remote_call endpoint has not been provisioned')
            self.state = 'requesting'
            room, request_id = 'PR-' + str(uuid.uuid4()), str(uuid.uuid4())
            a = self.reader.state['adoption']
            now = int(time.time())
            location = p.get('location', {})
            body = {'request_id': request_id, 'agora_channel': room, 'room_id': room,
                    'controller_id': a['controller_id'], 'device_id': self.reader.state['id'],
                    'device_name': a.get('name', 'Access Software PoC'),
                    'door_name': p.get('door_name', ''), 'floor_name': location.get('parent', {}).get('name', ''),
                    'in_or_out': p.get('in_or_out', 'in'), 'mode': 'webrtc',
                    'create_time': now, 'create_time_uid': now, 'notify_door_guards': []}
            try:
                result = await self.request('POST', endpoint, body)
                if not isinstance(result, dict) or not result.get('token'):
                    raise CallError('No call token returned')
                # Inspected WebRtcController ignores the Agora token argument and
                # joins its generated room through the controller WebSocket.
                await self._start_room(room)
                self.reader.event('call_requested')
            except BaseException:
                await self.hangup()
                raise
        return self.status()

    async def remote_view(self, data):
        room = data.get('room_id')
        if not isinstance(room, str) or not room:
            raise CallError('Only WebRTC room_id sessions are implemented')
        if data.get('device_id') not in (None, '', self.reader.state['id']):
            raise CallError('Remote view targets another device')
        async with self.lock:
            if self.room == room and self.pc:
                return
            if self.state == 'waiting_for_receiver':
                # Access opens a separate room when a receiver views a ringing
                # reader. Move the unconnected caller into that authorized room.
                await self.hangup(notify=False)
                self.reader.event('call_room_handoff')
            if self.state != 'idle':
                raise CallError('A call is already active')
            try:
                await self._start_room(room)
            except BaseException:
                await self.hangup()
                raise

    async def _start_room(self, room):
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', room):
            raise CallError('Invalid room ID')
        p = self.provisioned()
        self.state = 'connecting'
        self.room = room
        self.frames_received = self.audio_energy = 0
        self.pending_ice = []
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=await self.ice_servers()))
        audio = self.reader.ems.audio
        self.pc.addTrack(BridgeAudioTrack(audio) if audio else Tone(440))
        self.pc.getTransceivers()[0].setCodecPreferences([c for c in RTCRtpSender.getCapabilities('audio').codecs if c.mimeType.lower() == 'audio/opus'])
        self.data_channel = self.pc.createDataChannel('pro-data')
        self.bind_data(self.data_channel)
        @self.pc.on('datachannel')
        def datachannel(channel):
            self.bind_data(channel)
        @self.pc.on('track')
        def track(track):
            if track.kind == 'audio':
                self.media_tasks.append(asyncio.create_task(self.consume_audio(track)))
        @self.pc.on('connectionstatechange')
        def change():
            state = self.pc.connectionState if self.pc else 'closed'
            self.reader.event('webrtc_state', state=state)
            if state == 'connected':
                self.state = 'connected'
            elif state in ('failed', 'closed') and self.state != 'idle':
                self.state = 'failed'
        url = scoped_url(p['origin'].replace('https://', 'wss://', 1) + '/api/v2/ws/signaling?roomId=' + quote(room, safe=''), self.reader.controller, self.reader.lab, websocket=True)
        self.ws = await (await self.client()).ws_connect(url, ssl=self.trust(), max_msg_size=262144,
                                                        timeout=ClientWSTimeout(ws_receive=90, ws_close=3))
        self.state = 'waiting_for_receiver'
        await self.ws.send_json({'action': 'ping'})
        self.task = asyncio.create_task(self.run_signalling())
        self.reader.event('signalling_connected')

    def bind_data(self, channel):
        @channel.on('message')
        def message(value):
            if not isinstance(value, str) or len(value) > 4096:
                return
            try:
                action = json.loads(value).get('action')
            except (ValueError, AttributeError):
                return
            if action == 'pickup':
                self.reader.event('call_picked_up')
                self.reader.call_lifecycle('answered')
            elif action in ('doorbell_view_destroyed', 'reach_max_live_time'):
                asyncio.create_task(self.hangup())
            # Camera and unlock commands have no implementation or side effects.

    async def consume_audio(self, track):
        resampler = av.AudioResampler(format='s16', layout='mono', rate=48000)
        try:
            while True:
                frame = await track.recv()
                self.frames_received += 1
                self.audio_energy += sum(abs(x) for x in array('h', bytes(frame.planes[0])))
                audio = self.reader.ems.audio
                if audio:
                    for pcm in resampler.resample(frame):
                        data = bytes(pcm.planes[0])[:pcm.samples * 2]
                        if hasattr(audio, 'record_incoming'):
                            audio.record_incoming(data, 'webrtc')
                        if audio.active:
                            audio.write_pcm(data, route='webrtc')
                if self.frames_received == 50:
                    self.reader.event('two_way_media_received', frames=50, nonzero=bool(self.audio_energy))
        except Exception:
            return

    async def offer(self):
        if self.pc.signalingState != 'stable' or self.pc.localDescription:
            return
        await self.pc.setLocalDescription(await self.pc.createOffer())
        await self.ws.send_json({'action': 'offer', 'payload': {'sdp': self.pc.localDescription.sdp}})
        self.reader.event('offer_sent')

    async def signal(self, data):
        action, payload = data.get('action'), data.get('payload') or {}
        if action == 'join':
            clients = payload.get('clientIds', [])
            if len(clients) == 2:
                await self.offer()
        elif action in ('answer', 'offer'):
            sdp = payload.get('sdp')
            if not isinstance(sdp, str) or len(sdp) > 131072:
                raise CallError('Invalid SDP')
            await self.pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=action))
            for candidate in self.pending_ice:
                await self.pc.addIceCandidate(candidate)
            self.pending_ice.clear()
            if action == 'offer':
                await self.pc.setLocalDescription(await self.pc.createAnswer())
                await self.ws.send_json({'action': 'answer', 'payload': {'sdp': self.pc.localDescription.sdp}})
            self.reader.event('remote_sdp_accepted', type=action)
        elif action == 'ice':
            ice = payload.get('ice') or {}
            text = ice.get('candidate', '')
            if not isinstance(text, str) or len(text) > 2048:
                raise CallError('Invalid ICE candidate')
            candidate = candidate_from_sdp(text.removeprefix('candidate:')) if text else None
            if candidate:
                candidate.sdpMid = ice.get('id')
                candidate.sdpMLineIndex = ice.get('label')
            if self.pc.remoteDescription:
                await self.pc.addIceCandidate(candidate)
            else:
                if len(self.pending_ice) >= 128:
                    raise CallError('Too many queued ICE candidates')
                self.pending_ice.append(candidate)
        elif action == 'time':
            await self.ws.send_json({'action': 'time', 'time': int(time.time() * 1000)})
        elif action == 'left':
            return False
        elif action not in ('ping', 'sync'):
            self.reader.event('signalling_unsupported_action')
        return True

    async def run_signalling(self):
        notify = True
        try:
            async for msg in self.ws:
                if msg.type in (WSMsgType.TEXT, WSMsgType.BINARY):
                    data = json.loads(msg.data)
                    if not isinstance(data, dict) or not await self.signal(data):
                        break
                elif msg.type == WSMsgType.ERROR:
                    raise CallError('WebSocket transport error')
        except asyncio.CancelledError:
            notify = False
            raise
        except Exception as exc:
            self.reader.event('signalling_failed', error_type=type(exc).__name__)
        finally:
            await self.hangup(from_task=True, notify=notify)

    async def hangup(self, from_task=False, notify=True):
        if notify:
            self.reader.call_lifecycle('ended')
        task, self.task = self.task, None
        if task and not from_task and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        ws, self.ws = self.ws, None
        pc, self.pc = self.pc, None
        if ws and not ws.closed:
            await ws.close()
        for t in self.media_tasks:
            t.cancel()
        await asyncio.gather(*self.media_tasks, return_exceptions=True)
        self.media_tasks.clear()
        if pc:
            await pc.close()
        self.room, self.state = None, 'idle'
        self.pending_ice.clear()

    async def close(self):
        await self.hangup()
        if self.http:
            await self.http.close()
