import asyncio
import tempfile
import unittest
from unittest.mock import Mock
from pathlib import Path
import wire
from virtual_hub import VirtualHub, VirtualLinkedReader


class HubTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.hub = VirtualHub(Path(self.temp.name) / 'hub', reader_id='02d5f80d93b0', port=8081, emit=False)
        self.assertEqual(self.hub.info()['model'], 'UAH')
        self.hub.state['adoption'] = {'controller_id': 'test-controller'}
        self.topic = self.hub.resource() + '/rpc/test/request'

    async def asyncTearDown(self):
        await self.hub.close()
        self.temp.cleanup()

    def request(self, path, body):
        _, packet = self.hub.rpc_reply(self.topic, wire.message({'path': path, 'requestId': '1'}, body))
        return wire.parse_message(packet)[0]

    def test_hub_profile_has_distinct_identity_and_correct_port(self):
        _, _, d = wire.parse_tlv(self.hub.discovery_packet())
        self.assertEqual(d[21], b'UAH')
        self.assertEqual(int.from_bytes(d[36], 'big'), 8081)
        self.assertNotEqual(d[33].decode(), self.hub.reader_id)
        attrs = dict(v.decode().split('=', 1) for t, v in wire.protobuf(self.hub.device_stat()) if t == 4)
        self.assertEqual(attrs['port'], '8081')
        self.assertEqual(attrs['port-mac-port2'], '02:d5:f8:0d:93:b0')

    async def test_native_unlock_command_auto_relocks_without_hardware(self):
        mqtt = self.hub.mqtt_client = Mock()
        mqtt.is_connected.return_value = True
        reply = self.request('/relay/unlock', wire.field(1, 'test-user') + wire.field(7, self.hub.reader_id))
        self.assertEqual(reply['code'], '0')
        self.assertTrue(self.hub.relay_unlocked)
        await asyncio.sleep(3.05)
        self.assertFalse(self.hub.relay_unlocked)
        self.assertEqual(self.hub.unlock_count, 1)
        self.assertTrue(all(not e['physical_actuation'] for e in self.hub.events if 'physical_actuation' in e))
        reports = []
        for call in mqtt.publish.call_args_list:
            topic, packet = call.args
            if topic.endswith('/input/state'):
                self.assertEqual(topic, self.hub.resource() + '/input/state')
                self.assertEqual(call.kwargs, {'qos': 0, 'retain': False})
                meta, body = wire.parse_message(packet)
                entities = [dict(wire.protobuf(v)) for t, v in wire.protobuf(body) if t == 1]
                reports.append({v[1].decode(): v[2] for v in entities})
        self.assertEqual([v['rly-lock_dry'] for v in reports], [1, 0])
        self.assertTrue(all(v['dps'] == 0 and v['EMERGY'] == 0 for v in reports))
        self.hub.mqtt_client = None

    def test_unlock_scope_and_malformed_commands_fail_closed(self):
        for body in (b'', wire.field(1, 'u') + wire.field(7, 'other-reader'),
                     wire.field(1, 'u') + wire.field(1, 'v'), wire.field(1, 'u') + b'\x18\x01'):
            self.assertNotEqual(self.request('/relay/unlock', body)['code'], '0')
            self.assertFalse(self.hub.relay_unlocked)
        with self.assertRaises(ValueError):
            self.hub.rpc_reply('/uctrl/other/device/other/rpc/x/request',
                               wire.message({'path': '/relay/unlock'}, wire.field(1, 'u')))
        self.assertEqual(self.hub.unlock_count, 0)

    def test_hub_config_revision_and_external_payload_rejection(self):
        body = b'\x08\x05' + wire.field(2, wire.field(1, 'alias') + wire.field(2, 'Virtual door'))
        self.assertEqual(self.request('/config/update', body)['code'], '0')
        self.assertEqual(self.hub.state['settings']['alias'], 'Virtual door')
        self.assertNotEqual(self.request('/config/update', b'\x08\x04')['code'], '0')
        self.assertNotEqual(self.request('/config/update', b'\x08\x06\x68\x01')['code'], '0')
        self.assertEqual(self.hub.state['provisioning']['revision'], 5)

    async def test_reader_reports_only_matching_virtual_hub(self):
        reader = VirtualLinkedReader(Path(self.temp.name) / 'reader', emit=False)
        self.hub.reader_id = reader.state['id']
        try:
            reader.associate_virtual_hub(self.hub)
            self.assertEqual(reader.info()['attrs']['uah_id'], self.hub.state['id'])
            attrs = dict(v.decode().split('=', 1) for t, v in wire.protobuf(reader.device_stat()) if t == 4)
            self.assertEqual(attrs['uah_id'], self.hub.state['id'])
            self.hub.reader_id = '02fffffffffe'
            with self.assertRaises(ValueError):
                reader.associate_virtual_hub(self.hub)
        finally:
            await reader.close()
