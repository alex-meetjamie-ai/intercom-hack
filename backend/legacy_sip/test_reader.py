import asyncio
import contextlib
import json
import ssl
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from aiohttp import ClientSession, ClientConnectorCertificateError
from reader import Reader
from security import make_cert, broker_target, load_state
import wire
import poc


def utf8(s):
    b = s.encode()
    return struct.pack('!H', len(b)) + b


def mqtt_packet(header, body):
    # MQTT's Remaining Length uses the same unsigned base-128 encoding.
    return bytes([header]) + wire.varint(len(body)) + body


async def read_packet(reader):
    header = (await reader.readexactly(1))[0]
    length = shift = 0
    for _ in range(4):
        b = (await reader.readexactly(1))[0]
        length |= (b & 127) << shift
        if b < 128:
            break
        shift += 7
    else:
        raise ValueError('invalid MQTT remaining length')
    if length > 1048576:
        raise ValueError('oversized fixture packet')
    return header, await reader.readexactly(length)


class BrokerFixture:
    """Tiny local MQTT test peer, not a production broker or Ubiquiti simulator."""
    def __init__(self, resource):
        self.resource = resource
        self.messages = asyncio.Queue()
        self.connections = asyncio.Queue()
        self.writer = None
        self.tasks = set()

    async def handler(self, reader, writer):
        task = asyncio.current_task(); self.tasks.add(task)
        self.writer = writer
        try:
            header, body = await read_packet(reader)
            assert header == 0x10 and body.startswith(b'\x00\x04MQTT\x04')
            self.connections.put_nowait(writer.get_extra_info('peercert'))
            writer.write(b'\x20\x02\x00\x00'); await writer.drain()
            while True:
                header, body = await read_packet(reader)
                if header == 0x82:
                    writer.write(b'\x90\x03' + body[:2] + b'\x00')
                    self.messages.put_nowait(('subscribe', body[4:-1].decode(), b''))
                elif header >> 4 == 3:
                    n = int.from_bytes(body[:2], 'big')
                    topic, payload = body[2:2+n].decode(), body[2+n:]
                    self.messages.put_nowait(('publish', topic, payload))
                elif header == 0xc0:
                    writer.write(b'\xd0\x00')
                elif header == 0xe0:
                    break
                else:
                    raise ValueError('unexpected fixture packet')
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()
            self.tasks.discard(task)

    async def send(self, path, payload=b''):
        topic = self.resource + '/rpc/lab-client/request'
        packet = wire.message({'path': path, 'requestId': 'request-1'}, payload)
        self.writer.write(mqtt_packet(0x30, utf8(topic) + packet))
        await self.writer.drain()

    async def next(self, suffix):
        while True:
            item = await asyncio.wait_for(self.messages.get(), 5)
            if item[1].endswith(suffix):
                return item

    async def close(self):
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)


class WireTests(unittest.TestCase):
    def test_bearer_known_vector_and_rejections(self):
        # Independent fixed vector generated with openssl MD5 for firmware formula.
        token = wire.auth_token('ubnt', 'ubnt', '12345')
        self.assertEqual(token, '12345b57733ab796da6a748d208f20abaa1be')
        self.assertTrue(wire.authorized('Bearer ' + token, [('ubnt', 'ubnt')]))
        self.assertFalse(wire.authorized('Basic ' + token, [('ubnt', 'ubnt')]))
        self.assertFalse(wire.authorized('Bearer ' + token, [('ubnt', 'wrong')]))

    def test_protobuf_known_vector(self):
        # Message { meta { key:"path", value:"/test" }, payloads:"hi" }
        expected = bytes.fromhex('0a0d0a047061746812052f7465737412026869')
        self.assertEqual(wire.message({'path': '/test'}, b'hi'), expected)
        self.assertEqual(wire.parse_message(expected), ({'path': '/test'}, b'hi'))
        for broken in (b'\x0a\xff', b'\x00', b'\x12\x06x', b'\x80'*11):
            with self.assertRaises(ValueError):
                wire.parse_message(broken)

    def test_discovery_golden_layout(self):
        state = {'id': '020304050607', 'adoption': None}
        packet = wire.discovery(state, '192.168.1.63', 8080, 7, 100)
        v, cmd, fields = wire.parse_tlv(packet)
        self.assertEqual((v, cmd), (1, 0))
        self.assertEqual(fields[2], bytes.fromhex('020304050607c0a8013f'))
        self.assertEqual(fields[36], bytes.fromhex('00001f90'))
        self.assertEqual(fields[23], b'\x01')
        self.assertEqual(fields[44], b'\x00')
        with self.assertRaises(ValueError):
            wire.parse_tlv(packet[:-1])
        state['adoption'] = {'controller_id': 'lab'}
        self.assertEqual(wire.parse_tlv(wire.discovery(state, '127.0.0.1', 8080, 0, 0))[2][23], b'\x00')

    def test_broker_scope(self):
        for address in ['ssl://other.example:12812', 'tcp://192.168.1.1:12812', 'ssl://192.168.1.1:443', 'ssl://user:pw@192.168.1.1:12812', 'ssl://192.168.1.1:12812/a']:
            with self.assertRaises(ValueError):
                broker_target(address, '192.168.1.1')
        for scheme in ('ssl', 'mqtts', 'tls'):
            self.assertEqual(broker_target(f'{scheme}://192.168.1.1:12812', '192.168.1.1'), ('192.168.1.1', 12812, True))

    def test_home_guard(self):
        def fake(args, **kwargs):
            from subprocess import CompletedProcess
            output = 'interface: en0\n' if 'route' in args[0] else '? (192.168.1.1) at aa:bb:cc:dd:ee:ff on en0'
            return CompletedProcess(args, 0, output, '')
        with patch('poc.subprocess.run', side_effect=fake):
            with self.assertRaisesRegex(RuntimeError, 'Office gateway identity not found'):
                poc.office_identity()


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.reader = Reader(self.root / 'reader', port=0, emit=False)
        await self.reader.start_http()
        self.session = ClientSession()
        self.client_ctx = ssl.create_default_context(cafile=str(self.root / 'reader/server.crt'))
        cert, key = make_cert(self.root / 'broker', '127.0.0.1', 'Local fixture CA')
        server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_ctx.load_cert_chain(cert, key)
        server_ctx.load_verify_locations(cert)
        server_ctx.verify_mode = ssl.CERT_REQUIRED
        self.broker = BrokerFixture(f"/uctrl/lab/device/{self.reader.state['id']}")
        self.server = await asyncio.start_server(self.broker.handler, '127.0.0.1', 0, ssl=server_ctx)
        port = self.server.sockets[0].getsockname()[1]
        self.adoption = {'controller_id': 'lab', 'name': 'Access Software PoC', 'ssh_user': 'poc-user',
                         'ssh_password': 'lab-secret-not-for-logs', 'broker_address': f'tls://127.0.0.1:{port}',
                         'broker_cert_ca': cert.read_text(), 'broker_cert': cert.read_text(), 'broker_priv_key': key.read_text(), 'extras': {}}

    async def asyncTearDown(self):
        await self.reader.close()
        self.server.close(); await self.server.wait_closed()
        await self.broker.close()
        await self.session.close()
        self.temp.cleanup()

    async def request(self, path, method='GET', data=None, adopted=False, token=None):
        if token is None:
            token = wire.auth_token('poc-user', self.adoption['ssh_password']) if adopted else wire.auth_token('ubnt', 'ubnt')
        async with self.session.request(method, f'https://127.0.0.1:{self.reader.port}{path}', json=data,
                                        ssl=self.client_ctx, headers={'Authorization': 'Bearer ' + token}) as response:
            return response.status, await response.json()

    async def adopt(self):
        code, body = await self.request('/api/v2/adopt', 'POST', self.adoption)
        self.assertEqual(code, 200)
        self.assertEqual(body['data']['attrs']['adopted'], 'true')
        peer = await asyncio.wait_for(self.broker.connections.get(), 5)
        self.assertIsNotNone(peer)  # Broker actually required a client certificate.
        await self.broker.next('/request')
        _, _, packet = await self.broker.next('/stat')
        meta, payload = wire.parse_message(packet)
        self.assertEqual(dict(wire.protobuf(payload))[1], self.reader.state['id'].encode())

    async def test_https_adoption_mtls_mqtt_rpc_and_restart(self):
        code, body = await self.request('/api/v2/info')
        self.assertEqual(code, 200)
        self.assertEqual(body['data']['model'], 'UA-G3-Pro')
        self.assertEqual(body['data']['attrs']['adopted'], 'false')
        await self.adopt()
        self.assertEqual((await self.request('/api/v2/info'))[0], 401)
        self.assertEqual((await self.request('/api/v2/info', adopted=True))[0], 200)
        self.assertEqual((await self.request('/api/v2/adopt', 'POST', self.adoption, adopted=True))[0], 400)
        await self.broker.send('/test')
        _, _, packet = await self.broker.next('/response')
        meta, body = wire.parse_message(packet)
        self.assertEqual((meta['requestId'], meta['code'], body), ('request-1', '0', b'hi'))
        await self.broker.send('/remote_open_door', b'secret credential data')
        _, _, packet = await self.broker.next('/response')
        self.assertEqual(wire.parse_message(packet)[0]['code'], '-2')
        self.assertNotIn('lab-secret-not-for-logs', json.dumps(self.reader.events))
        self.assertNotIn('secret credential data', json.dumps(self.reader.events))
        original_id = self.reader.state['id']
        await self.reader.close()
        self.reader = Reader(self.root / 'reader', port=0, emit=False)
        await self.reader.start_http()
        await asyncio.wait_for(self.broker.connections.get(), 5)
        await self.broker.next('/request')
        await self.broker.next('/stat')
        self.assertEqual(self.reader.state['id'], original_id)
        self.assertEqual((self.root/'reader/state.json').stat().st_mode & 0o777, 0o600)

    async def test_auth_failure_and_failed_adoption_are_atomic(self):
        self.assertEqual((await self.request('/api/v2/info', token='bad'))[0], 401)
        bad = dict(self.adoption, broker_address='ssl://unrelated.example:12812')
        self.assertEqual((await self.request('/api/v2/adopt', 'POST', bad))[0], 400)
        self.assertIsNone(self.reader.state['adoption'])
        self.assertIsNone(load_state(self.root/'reader')['adoption'])
        self.assertIsNone(self.reader.mqtt_client)
        self.assertEqual((await self.request('/api/v2/dev/verify', 'POST', {}))[0], 404)

    async def test_tls_rejects_untrusted_server_certificate(self):
        loop = asyncio.get_running_loop()
        previous = loop.get_exception_handler()
        def expected_reset(loop, context):
            if not isinstance(context.get('exception'), ConnectionResetError):
                (previous or (lambda l, c: l.default_exception_handler(c)))(loop, context)
        loop.set_exception_handler(expected_reset)
        with self.assertRaises(ClientConnectorCertificateError):
            async with self.session.get(f'https://127.0.0.1:{self.reader.port}/api/v2/info') as response:
                await response.read()

    async def test_broker_fingerprint_mismatch_prevents_stat(self):
        self.adoption['extras']['mqtt_cert_fingerprint'] = '00' * 32
        self.assertEqual((await self.request('/api/v2/adopt', 'POST', self.adoption))[0], 200)
        await asyncio.wait_for(self.broker.connections.get(), 5)
        for _ in range(40):
            if any(e['event'] == 'mqtt_rejected' for e in self.reader.events):
                break
            await asyncio.sleep(.05)
        self.assertTrue(any(e['event'] == 'mqtt_rejected' for e in self.reader.events))
        self.assertFalse(any(e['event'] == 'stat_sent' for e in self.reader.events))


if __name__ == '__main__':
    unittest.main(verbosity=2)
