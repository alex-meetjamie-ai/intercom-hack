import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from aiohttp import ClientSession
from audio_io import ToneAudio, SILENCE
from reader import Reader
from sks_bridge import SimulatedSks, SksBridge
from virtual_hub import VirtualHub
import wire


class SksModelTests(unittest.TestCase):
    def test_window_does_not_extend_on_bounce_and_retries_do_not_actuate(self):
        now = [10.0]
        sks = SimulatedSks(window=120, clock=lambda: now[0])
        with self.assertRaises(ValueError):
            sks.release('before-ring')
        self.assertTrue(sks.ring())
        now[0] += 100
        self.assertFalse(sks.ring())
        sks.answer()
        self.assertTrue(sks.release('first'))
        self.assertFalse(sks.release('first'))
        self.assertEqual(sks.releases, 1)
        now[0] = 130
        with self.assertRaises(ValueError):
            sks.release('late')
        sks.end()
        self.assertFalse(sks.relay)
        self.assertTrue(sks.ring())
        self.assertFalse(sks.release('first'))
        self.assertTrue(sks.release('second'))
        self.assertEqual(sks.releases, 2)
        fresh = SimulatedSks()
        with self.assertRaises(ValueError):
            fresh.release('first')


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.reader = Reader(self.root / 'reader', emit=False)
        self.reader.calls.ring = AsyncMock(return_value={})
        self.reader.calls.hangup = AsyncMock()
        self.hub = VirtualHub(self.root / 'hub', reader_id=self.reader.state['id'], emit=False)
        self.hub.state['adoption'] = self.reader.state['adoption'] = {'controller_id': 'test'}
        self.audio = ToneAudio()
        self.bridge = SksBridge(self.reader, self.hub, self.audio)

    async def asyncTearDown(self):
        await self.reader.close()
        await self.hub.close()
        self.temp.cleanup()

    def unlock(self, request='one'):
        _, result = self.hub.rpc_reply(self.hub.resource() + '/rpc/test/request',
            wire.message({'path': '/relay/unlock', 'requestId': request},
                         wire.field(1, 'test-user') + wire.field(7, self.reader.state['id'])))
        return wire.parse_message(result)[0]['code']

    async def test_local_control_ring_native_pickup_unlock_and_hangup(self):
        await self.reader.start_control()
        control = json.loads((self.reader.folder / 'control.json').read_text())
        headers = {'Authorization': 'Bearer ' + control['token']}
        self.assertNotEqual(self.unlock(), '0')
        async with ClientSession() as client:
            async with client.post(control['url'] + '/sks-answer') as response:
                self.assertEqual(response.status, 401)
            async with client.post(control['url'] + '/sks-answer', headers=headers) as response:
                self.assertEqual(response.status, 409)
            for _ in range(2):
                async with client.post(control['url'] + '/ring', headers=headers) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual((await response.json())['sks']['state'], 'ringing')
            self.reader.calls.ring.assert_awaited_once()
            self.assertEqual(self.audio.read_pcm(), SILENCE)
            _, reply = self.reader.rpc_reply(self.reader.resource() + '/rpc/test/request',
                wire.message({'path': '/remote_call_is_talked', 'requestId': 'pickup'}, b''))
            self.assertEqual(wire.parse_message(reply)[0]['code'], '0')
            self.assertEqual(self.bridge.adapter.state, 'answered')
            self.assertNotEqual(self.audio.read_pcm(), SILENCE)
            self.assertEqual(self.unlock(), '0')
            pulse = self.hub.relock_handle
            self.assertEqual(self.unlock(), '0')
            self.assertIs(self.hub.relock_handle, pulse)
            self.assertEqual(self.hub.unlock_count, 1)
            self.assertEqual(self.bridge.adapter.releases, 1)
            async with client.post(control['url'] + '/hangup', headers=headers) as response:
                self.assertEqual(response.status, 200)
            self.assertEqual(self.audio.read_pcm(), SILENCE)
            self.assertFalse(self.hub.relay_unlocked)
            self.assertTrue(pulse.cancelled())
            self.assertNotEqual(self.unlock('late'), '0')

    async def test_timeout_mutes_audio_relocks_and_ends_call(self):
        self.bridge.adapter.window = .05
        await self.bridge.ring()
        self.bridge.answer()
        self.assertEqual(self.unlock(), '0')
        await asyncio.sleep(.09)
        self.assertFalse(self.audio.active)
        self.assertEqual(self.bridge.adapter.state, 'idle')
        self.assertFalse(self.hub.relay_unlocked)
        self.reader.calls.hangup.assert_awaited()
        self.assertNotEqual(self.unlock('after-expiry'), '0')

    async def test_failed_ring_and_transport_loss_close_unlock_window(self):
        self.reader.calls.ring.side_effect = RuntimeError('offline')
        with self.assertRaises(RuntimeError):
            await self.bridge.ring()
        self.assertFalse(self.bridge.adapter.is_live())
        self.assertIsNone(self.bridge.timer)
        self.reader.calls.ring.side_effect = None
        await self.bridge.ring()
        self.bridge.answer()
        self.assertEqual(self.unlock(), '0')
        self.hub.call_lifecycle('transport_failed')
        self.assertFalse(self.audio.active)
        self.assertFalse(self.hub.relay_unlocked)
        await asyncio.sleep(0)
        self.reader.calls.hangup.assert_awaited()
        self.assertNotEqual(self.unlock('offline'), '0')

    async def test_expiry_while_controller_is_starting_cleans_up_late_session(self):
        self.bridge.adapter.window = .02
        async def slow_ring():
            await asyncio.sleep(.05)
        self.reader.calls.ring.side_effect = slow_ring
        with self.assertRaisesRegex(ValueError, 'ended before ringing completed'):
            await self.bridge.ring()
        self.assertFalse(self.audio.active)
        self.assertFalse(self.bridge.adapter.is_live())
        self.assertGreaterEqual(self.reader.calls.hangup.await_count, 2)


if __name__ == '__main__':
    unittest.main()
