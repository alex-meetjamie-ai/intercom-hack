import asyncio
import contextlib
import copy
import json
import ssl
import unittest
from array import array
from unittest.mock import patch
from aiohttp import web, WSMsgType
from aiortc import RTCPeerConnection, RTCConfiguration, RTCSessionDescription
import test_reader as fixtures
from media_lab import Tone
from native_calls import CallError
from provisioning import encode, decode, apply_tokens, apply_configs
from security import load_state
import wire


class ProvisioningTests(unittest.TestCase):
    def test_independent_config_golden_vector(self):
        # UpdateConfigs { configs { key:"volume", value:"40" } }
        packet = bytes.fromhex('0a0c0a06766f6c756d6512023430')
        self.assertEqual(decode('UpdateConfigs', packet), {'configs': [{'key': 'volume', 'value': '40'}]})
        self.assertEqual(apply_configs({}, packet)['settings'], {'volume': '40'})

    def test_invalid_update_is_atomic_and_nested_payload_bounded(self):
        state = {'settings': {'volume': '20'}, 'provisioning': {'revision': 3}}
        original = copy.deepcopy(state)
        packet = encode('DAUpdate', {'revision': 4, 'config': {'controller_host': 'other.example'}})
        with self.assertRaises(ValueError):
            apply_tokens(state, packet, '127.0.0.1', True)
        self.assertEqual(state, original)
        recursive = b''
        for _ in range(15):
            recursive = wire.field(4, recursive)
        with self.assertRaisesRegex(ValueError, 'nesting limit'):
            decode('Location', recursive)
        with self.assertRaises(ValueError):
            apply_tokens(state, encode('DAUpdate', {'revision': 2, 'config': {}}), '127.0.0.1', True)


class CallsIntegrationTests(unittest.IsolatedAsyncioTestCase):
    # Reuse the actual HTTPS + mTLS broker fixture without inheriting/re-running its tests.
    request = fixtures.IntegrationTests.request
    adopt = fixtures.IntegrationTests.adopt

    async def asyncSetUp(self):
        self.ice_patch = patch('aioice.ice.get_host_addresses', return_value=['127.0.0.1'])
        self.ice_patch.start()
        await fixtures.IntegrationTests.asyncSetUp(self)
        self.frames = 0
        self.energy = 0
        self.rings = []
        self.peers = set()
        self.ws_clients = set()
        self.fixture_tasks = set()
        self.inject_early_ice = True
        self.bad_ice_response = False
        self.chunked_ice_response = False
        self.oversized_ice_response = False
        self.redirect_signalling = False
        self.redirect_followed = False
        self.hold_join = False
        app = web.Application()
        app.router.add_post('/api/v2/lab/remote_call', self.ring_endpoint)
        app.router.add_get('/api/v2/lab/ice', self.ice_endpoint)
        app.router.add_get('/api/v2/ws/signaling', self.signalling_endpoint)
        app.router.add_get('/redirect-target', self.redirect_target)
        self.call_runner = web.AppRunner(app, access_log=None)
        await self.call_runner.setup()
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.root / 'broker/server.crt', self.root / 'broker/server.key')
        site = web.TCPSite(self.call_runner, '127.0.0.1', 0, ssl_context=ctx)
        await site.start()
        self.call_port = site._server.sockets[0].getsockname()[1]
        self.update = {'revision': 7, 'config_url': 'https://127.0.0.1/unused-config-download', 'config': {
            'controller_host': '127.0.0.1', 'controller_port': self.call_port,
            'access_token': 'lab-agent-token-private', 'door_name': 'Test door',
            'location': {'id': 'lab-door', 'name': 'Test door', 'parent': {'name': 'Test floor'}},
            'api_endpoint': [{'key': 'remote_call', 'value': '/api/v2/lab/remote_call', 'method': 'POST'},
                             {'key': 'ice_credentials', 'value': '/api/v2/lab/ice', 'method': 'GET'}],
            'configs': [{'key': 'volume', 'value': '40'}]},
            'tokens': [{'type': 'test', 'value': 'private-test-token', 'worker_id': 'test-only', 'granted': True}]}

    async def asyncTearDown(self):
        await self.reader.calls.close()
        for ws in list(self.ws_clients):
            await ws.close()
        for pc in list(self.peers):
            await pc.close()
        for task in list(self.fixture_tasks):
            task.cancel()
        await asyncio.gather(*list(self.fixture_tasks), return_exceptions=True)
        await self.call_runner.cleanup()
        await fixtures.IntegrationTests.asyncTearDown(self)
        self.ice_patch.stop()

    async def ring_endpoint(self, request):
        if request.headers.get('Authorization') != 'Bearer lab-agent-token-private':
            return web.json_response({'code': 1}, status=401)
        body = await request.json()
        self.rings.append(body)
        return web.json_response({'code': 1, 'codeS': 'SUCCESS', 'data': {'token': 'fixture-only-call-token'}})

    async def ice_endpoint(self, request):
        if request.headers.get('Authorization') != 'Bearer lab-agent-token-private':
            return web.json_response({'code': 1}, status=401)
        if self.bad_ice_response:
            return web.json_response({'code': 1}, status=503)
        if self.oversized_ice_response:
            return web.Response(body=b' ' * 1048577)
        if self.chunked_ice_response:
            response = web.StreamResponse(headers={'Content-Type': 'application/json'})
            await response.prepare(request)
            await response.write(b'{"code": 0, "data":')
            await asyncio.sleep(.02)
            await response.write(b'{"local": {"uris": []}}}')
            await response.write_eof()
            return response
        return web.json_response({'code': 1, 'codeS': 'SUCCESS', 'data': {'local': {'uris': [], 'username': '', 'password': ''}}})

    async def redirect_target(self, request):
        self.redirect_followed = True
        return web.Response()

    async def consume(self, track):
        try:
            while True:
                frame = await track.recv()
                self.frames += 1
                self.energy += sum(abs(x) for x in array('h', bytes(frame.planes[0])))
        except Exception:
            pass

    async def signalling_endpoint(self, request):
        if self.redirect_signalling:
            raise web.HTTPFound('/redirect-target')
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.ws_clients.add(ws)
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        pc.addTrack(Tone(660))
        self.peers.add(pc)
        @pc.on('track')
        def track(track):
            task = asyncio.create_task(self.consume(track))
            self.fixture_tasks.add(task)
            task.add_done_callback(self.fixture_tasks.discard)
        @pc.on('datachannel')
        def channel(channel):
            @channel.on('open')
            def open_channel():
                channel.send(json.dumps({'action': 'pickup'}))
        try:
            clients = ['reader'] if self.hold_join else ['reader', 'receiver']
            await ws.send_json({'action': 'join', 'payload': {'clientIds': clients}})
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                data = json.loads(msg.data)
                if data['action'] == 'offer':
                    await pc.setRemoteDescription(RTCSessionDescription(sdp=data['payload']['sdp'], type='offer'))
                    await pc.setLocalDescription(await pc.createAnswer())
                    sdp = pc.localDescription.sdp
                    self.assertTrue(all(' 127.0.0.1 ' in line for line in sdp.splitlines() if line.startswith('a=candidate:')))
                    if self.inject_early_ice:
                        candidate = next(line[2:] for line in sdp.splitlines() if line.startswith('a=candidate:'))
                        await ws.send_json({'action': 'ice', 'payload': {'ice': {'candidate': candidate, 'id': '0', 'label': 0}}})
                    await ws.send_json({'action': 'answer', 'payload': {'sdp': sdp}})
                elif data['action'] == 'ping':
                    await ws.send_json({'action': 'ping'})
        finally:
            await pc.close()
            self.peers.discard(pc)
            self.ws_clients.discard(ws)
        return ws

    async def provision(self):
        await self.adopt()
        await self.broker.send('/update_tokens', encode('DAUpdate', self.update))
        _, _, packet = await self.broker.next('/response')
        self.assertEqual(wire.parse_message(packet)[0]['code'], '0')
        self.assertEqual(self.reader.info()['attrs']['revision'], '7')

    async def wait_audio(self):
        for _ in range(100):
            if self.frames >= 50 and self.reader.calls.frames_received >= 50:
                break
            await asyncio.sleep(.1)
        self.assertGreaterEqual(self.frames, 50)
        self.assertGreaterEqual(self.reader.calls.frames_received, 50)
        self.assertGreater(self.energy, 0)
        self.assertGreater(self.reader.calls.audio_energy, 0)
        self.assertEqual(self.reader.calls.state, 'connected')

    async def test_provision_ring_signalling_audio_hangup(self):
        await self.provision()
        await self.reader.start_control()
        control = json.loads((self.root / 'reader/control.json').read_text())
        headers = {'Authorization': 'Bearer ' + control['token']}
        async with self.session.post(control['url'] + '/ring', headers=headers) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())['source'], 'generated tone')
        await self.wait_audio()
        self.assertEqual(len(self.rings), 1)
        self.assertEqual(self.rings[0]['device_id'], self.reader.state['id'])
        self.assertEqual(self.rings[0]['mode'], 'webrtc')
        self.assertEqual(self.rings[0]['floor_name'], 'Test floor')
        for secret in ('lab-agent-token-private', 'private-test-token', 'fixture-only-call-token'):
            self.assertNotIn(secret, json.dumps(self.reader.events))
        persisted = load_state(self.root / 'reader')
        self.assertEqual(persisted['provisioning']['revision'], 7)
        self.assertEqual(persisted['settings']['volume'], '40')
        async with self.session.post(control['url'] + '/hangup', headers=headers) as response:
            self.assertEqual(response.status, 200)
        self.assertEqual(self.reader.calls.state, 'idle')
        self.assertIsNone(self.reader.calls.pc)

    async def test_mqtt_remote_view_and_peer_hangup(self):
        await self.provision()
        await self.broker.send('/remote_view', encode('DARemoteView', {'room_id': 'lab-remote-view', 'device_id': self.reader.state['id']}))
        _, _, packet = await self.broker.next('/response')
        self.assertEqual(wire.parse_message(packet)[0]['code'], '0')
        await self.wait_audio()
        await self.broker.send('/check_is_remote_view_on')
        _, _, packet = await self.broker.next('/response')
        self.assertEqual(wire.parse_message(packet)[0]['code'], '0')
        for ws in list(self.ws_clients):
            await ws.send_json({'action': 'left'})
        for _ in range(50):
            if self.reader.calls.state == 'idle':
                break
            await asyncio.sleep(.05)
        self.assertEqual(self.reader.calls.state, 'idle')
        self.assertEqual(self.rings, [])  # Viewing does not ring recipients.

    async def test_receiver_handoff_from_ringing_to_new_view_room(self):
        from types import SimpleNamespace
        from audio_io import ToneAudio
        from sks_bridge import SksBridge
        await self.provision()
        bridge = SksBridge(self.reader, SimpleNamespace(relay_unlocked=False), ToneAudio())
        self.hold_join = True
        await bridge.ring()
        self.assertEqual(self.reader.calls.state, 'waiting_for_receiver')
        old_peer = self.reader.calls.pc
        self.hold_join = False
        await self.broker.send('/remote_view', encode('DARemoteView', {
            'room_id': 'PR-receiver-view-room', 'device_id': self.reader.state['id']}))
        _, _, packet = await self.broker.next('/response')
        self.assertEqual(wire.parse_message(packet)[0]['code'], '0')
        self.assertEqual(old_peer.connectionState, 'closed')
        self.assertEqual(self.reader.calls.room, 'PR-receiver-view-room')
        self.assertEqual(len(self.rings), 1)
        self.assertTrue(bridge.adapter.is_live())
        # Exercise the firmware's pickup RPC and a real receiver hangup, across
        # the old-room teardown, rather than inferring pickup from video viewing.
        await self.broker.send('/remote_call_is_talked')
        _, _, packet = await self.broker.next('/response')
        self.assertEqual(wire.parse_message(packet)[0]['code'], '0')
        self.assertTrue(bridge.audio.active)
        await self.wait_audio()
        self.assertGreater(bridge.audio.received_samples, 0)
        for ws in list(self.ws_clients):
            await ws.send_json({'action': 'left'})
        for _ in range(50):
            if not bridge.adapter.is_live():
                break
            await asyncio.sleep(.02)
        self.assertFalse(bridge.audio.active)
        self.assertFalse(bridge.adapter.is_live())

    async def test_control_auth_missing_provisioning_and_settings_rpc(self):
        await self.reader.start_control()
        control = json.loads((self.root / 'reader/control.json').read_text())
        async with self.session.post(control['url'] + '/ring') as response:
            self.assertEqual(response.status, 401)
        async with self.session.post(control['url'] + '/ring', headers={'Authorization': 'Bearer ' + control['token']}) as response:
            self.assertEqual(response.status, 409)
        self.assertEqual(self.rings, [])
        await self.provision()
        await self.broker.send('/update_configs', encode('UpdateConfigs', {'configs': [{'key': 'volume', 'value': '25'}]}))
        _, _, packet = await self.broker.next('/response')
        self.assertEqual(wire.parse_message(packet)[0]['code'], '0')
        self.assertEqual((await self.request('/api/v2/get_configs', adopted=True))[1]['data']['volume'], '25')
        bad = copy.deepcopy(self.update)
        bad['config']['controller_host'] = 'unrelated.example'
        await self.broker.send('/update_tokens', encode('DAUpdate', bad))
        _, _, packet = await self.broker.next('/response')
        self.assertEqual(wire.parse_message(packet)[0]['code'], '1')
        self.assertEqual(self.reader.state['provisioning']['revision'], 7)

    async def test_failed_call_closes_partial_session(self):
        await self.provision()
        self.bad_ice_response = True
        with self.assertRaisesRegex(CallError, 'HTTP status 503'):
            await self.reader.calls.remote_view({'room_id': 'lab-failed-call'})
        self.assertEqual(self.reader.calls.state, 'idle')
        self.assertIsNone(self.reader.calls.pc)
        self.assertIsNone(self.reader.calls.ws)

    async def test_call_provisioning_survives_restart(self):
        await self.provision()
        device_id = self.reader.state['id']
        await self.reader.close()
        self.reader = fixtures.Reader(self.root / 'reader', port=0, emit=False)
        await self.reader.start_http()
        await asyncio.wait_for(self.broker.connections.get(), 5)
        await self.broker.next('/request')
        await self.broker.next('/stat')
        self.assertEqual(self.reader.state['id'], device_id)
        self.assertEqual(self.reader.info()['attrs']['revision'], '7')
        # No second adoption or provisioning update is sent.
        await self.reader.calls.ring()
        await self.wait_audio()
        self.assertEqual(len(self.rings), 1)

    async def test_chunked_http_and_size_limit(self):
        await self.provision()
        self.chunked_ice_response = True
        self.assertEqual(await self.reader.calls.ice_servers(), [])
        self.oversized_ice_response = True
        with self.assertRaisesRegex(CallError, 'response too large'):
            await self.reader.calls.ice_servers()

    async def test_websocket_redirect_never_followed(self):
        await self.provision()
        self.redirect_signalling = True
        with self.assertRaisesRegex(CallError, 'redirects are not supported'):
            await self.reader.calls.remote_view({'room_id': 'lab-redirect'})
        self.assertFalse(self.redirect_followed)
        self.assertIsNone(self.reader.calls.pc)
        self.assertIsNone(self.reader.calls.ws)
        self.assertEqual(self.reader.calls.state, 'idle')


if __name__ == '__main__':
    unittest.main(verbosity=2)
