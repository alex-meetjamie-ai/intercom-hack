"""Offline SKS adapter lab. Only authenticated loopback control is opened.

The upstream call controller is a stub. Unlocks traverse the actual virtual-hub
RPC validation, but this does not ring office receivers or validate SKS wiring.
"""
import asyncio
import json
import signal
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout
from audio_io import ToneAudio, SILENCE
from reader import Reader
from sks_adapter import SimulatedSks
from sks_bridge import SksBridge
from virtual_hub import VirtualHub
import wire


class LabCalls:
    def __init__(self):
        self.state, self.rings, self.hangups = 'idle', 0, 0
        self.delay = 0

    async def ring(self):
        self.rings += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        self.state = 'ringing'
        return self.status()

    async def hangup(self):
        self.hangups += 1
        self.state = 'idle'

    async def close(self):
        await self.hangup()

    def status(self):
        return {'state': self.state, 'upstream': 'offline_controller_stub',
                'ring_requests': self.rings, 'hangup_requests': self.hangups}


class SksLab:
    def __init__(self, folder, window=120, after_release=10):
        root = Path(folder)
        self.reader = Reader(root / 'reader', emit=False)
        if self.reader.state.get('adoption'):
            raise ValueError('SKS lab cannot use an adopted reader state')
        self.hub = VirtualHub(root / 'hub', reader_id=self.reader.state['id'], emit=False)
        if self.hub.state.get('adoption'):
            raise ValueError('SKS lab cannot use an adopted hub state')
        # In-memory fixture credentials only; never start MQTT/discovery/EMS.
        self.reader.state['adoption'] = self.hub.state['adoption'] = {'controller_id': 'sks-lab'}
        self.reader.calls = self.calls = LabCalls()
        self.audio = ToneAudio()
        self.bridge = SksBridge(self.reader, self.hub, self.audio,
                               adapter=SimulatedSks(window, after_release=after_release))
        self.reader.lab_controls = self.native_control

    async def start(self):
        await self.reader.start_control()
        self.control = json.loads((self.reader.folder / 'control.json').read_text())
        return self

    def native_control(self, path, data):
        if path == '/sim-pickup':
            if not isinstance(data, dict) or set(data) != {'call_id'} or not isinstance(data['call_id'], str):
                raise ValueError('Expected a call_id')
            self.bridge.answer(data['call_id'])
            self.calls.state = 'answered'
        elif path == '/sim-unlock':
            if not isinstance(data, dict) or set(data) != {'request_id'}:
                raise ValueError('Expected a request_id')
            request_id = data['request_id']
            if not isinstance(request_id, str) or not 0 < len(request_id) <= 256:
                raise ValueError('Invalid request_id')
            topic = self.hub.resource() + '/rpc/sks-lab/request'
            packet = wire.message({'path': '/relay/unlock', 'requestId': request_id},
                wire.field(1, 'simulated-user') + wire.field(7, self.reader.state['id']))
            _, reply = self.hub.rpc_reply(topic, packet)
            if wire.parse_message(reply)[0]['code'] != '0':
                raise ValueError('Simulated native Unlock was rejected')
        else:
            raise ValueError('Unknown lab control')
        return {**self.bridge.status(), **self.calls.status()}

    async def close(self):
        await self.reader.close()
        await self.hub.close()


async def serve(args):
    lab = SksLab(args.state)
    try:
        await lab.start()
        print('Offline SKS lab ready; no office connection or microphone. Control state:',
              str(lab.reader.folder.resolve()), flush=True)
        done = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig, done.set)
        try:
            await asyncio.wait_for(done.wait(), args.minutes * 60)
        except asyncio.TimeoutError:
            pass
    finally:
        await lab.close()
        print('Stopped offline SKS lab.', flush=True)


def require(condition, message):
    if not condition:
        raise RuntimeError('Scenario failed: ' + message)


async def run_scenarios():
    results = []
    names = ('normal_call', 'unrelated_bells', 'missed_call', 'line_loss',
             'duplicate_and_busy', 'stale_events', 'command_failures', 'slow_controller')
    for name in names:
        with tempfile.TemporaryDirectory(prefix='sks-simulation-') as folder:
            lab = SksLab(folder, window=.08 if name in ('missed_call', 'slow_controller') else 120,
                         after_release=.08 if name == 'normal_call' else 10)
            try:
                await lab.start()
                async with ClientSession(timeout=ClientTimeout(total=5), trust_env=False) as client:
                    async def request(path, data=None, status=200, authorized=True):
                        headers = {'Authorization': 'Bearer ' + lab.control['token']} if authorized else {}
                        async with client.post(lab.control['url'] + path, json=data, headers=headers,
                                               allow_redirects=False) as response:
                            result = await response.json()
                            require(response.status == status, f'{name}: {path} status {response.status}')
                            return result

                    async def event(kind, call_id=None, **kwargs):
                        data = {'event': kind}
                        if call_id is not None:
                            data['call_id'] = call_id
                        return await request('/sks-event', data, **kwargs)

                    async def pickup(call_id='call-a', **kwargs):
                        return await request('/sim-pickup', {'call_id': call_id}, **kwargs)

                    async def unlock(request_id='unlock-a', **kwargs):
                        return await request('/sim-unlock', {'request_id': request_id}, **kwargs)

                    await event('door-call', 'unauthorized', status=401, authorized=False)
                    require(lab.calls.rings == 0, 'unauthorized input rang controller')
                    if name == 'unrelated_bells':
                        for kind in ('floor-call', 'internal-call', 'other-tenant'):
                            require(not (await event(kind))['accepted'], 'unrelated bell accepted')
                        await request('/sks-event', {'event': 'unknown'}, status=409)
                        await request('/sks-event', {'event': 'door-call', 'call_id': 'a', 'voltage': 22}, status=409)
                        await unlock(status=409)
                        require(lab.calls.rings == 0 and not lab.audio.active, 'unrelated bell enabled bridge')
                    elif name == 'slow_controller':
                        lab.calls.delay = .15
                        await event('door-call', 'call-a', status=409)
                        require(lab.calls.state == 'idle' and not lab.bridge.adapter.is_live(), 'late session survived')
                    else:
                        await event('door-call', 'call-a')
                        require(lab.audio.read_pcm() == SILENCE, 'audio active before pickup')
                        if name == 'normal_call':
                            await pickup()
                            require(lab.audio.read_pcm() != SILENCE, 'answer did not enable audio')
                            await unlock()
                            require(lab.hub.relay_unlocked, 'release failed')
                            await asyncio.sleep(.13)
                            require(not lab.audio.active and not lab.hub.relay_unlocked, 'post-release expiry failed')
                            await unlock('after-expiry', status=409)
                        elif name == 'missed_call':
                            await asyncio.sleep(.13)
                            await pickup(status=409)
                            await unlock(status=409)
                            require(lab.calls.state == 'idle' and not lab.audio.active, 'missed call survived')
                        elif name == 'line_loss':
                            await pickup()
                            await unlock()
                            await event('line-lost')
                            require(not lab.audio.active and not lab.hub.relay_unlocked, 'line loss left outputs active')
                            await event('door-call', 'call-b', status=409)
                            await unlock('offline', status=409)
                            await event('line-restored')
                            await pickup(status=409)
                            require(not lab.bridge.adapter.is_live(), 'reconnect resurrected call')
                            require(not (await event('door-call', 'call-a'))['accepted'], 'old call replayed')
                            await event('door-call', 'call-b')
                            await pickup('call-b')
                        elif name == 'duplicate_and_busy':
                            deadline = lab.bridge.adapter.deadline
                            require(not (await event('door-call', 'call-a'))['accepted'], 'duplicate ring accepted')
                            require(not (await event('door-call', 'call-b'))['accepted'], 'busy ring accepted')
                            require(lab.calls.rings == 1 and lab.bridge.adapter.deadline == deadline, 'ring extended call')
                            await pickup()
                            await pickup()
                            await unlock()
                            pulse, deadline = lab.hub.relock_handle, lab.bridge.adapter.deadline
                            await unlock()
                            await unlock('another-click')
                            require(lab.hub.relock_handle is pulse and lab.bridge.adapter.deadline == deadline,
                                    'repeated unlock extended pulse or call')
                            require(lab.bridge.adapter.releases == 1, 'duplicate release occurred')
                            # Exercise the actual fixed three-second hub timer.
                            await asyncio.sleep(3.1)
                            require(not lab.hub.relay_unlocked and lab.audio.active, 'relock broke audio or failed')
                            await unlock('another-click')
                            require(lab.bridge.adapter.releases == 1, 'coalesced request replayed')
                        elif name == 'stale_events':
                            await pickup()
                            await event('visitor-left', 'call-a')
                            await event('door-call', 'call-b')
                            await pickup('call-a', status=409)
                            require(not (await event('visitor-left', 'call-a'))['accepted'], 'stale end accepted')
                            require(lab.bridge.adapter.call_id == 'call-b', 'stale event ended new call')
                            await pickup('call-b')
                        elif name == 'command_failures':
                            await event('fail-next-answer')
                            await pickup(status=409)
                            require(not lab.audio.active and not lab.bridge.adapter.online, 'failed answer enabled audio')
                            await event('line-restored')
                            await event('door-call', 'call-b')
                            await pickup('call-b')
                            await event('fail-next-release')
                            await unlock(status=409)
                            require(lab.hub.unlock_count == 0 and not lab.audio.active,
                                    'failed release reported success or left audio active')
                    await request('/hangup')
                    require(not lab.audio.active and not lab.hub.relay_unlocked, 'final cleanup failed')
                    results.append({'scenario': name, 'result': 'passed',
                                    'upstream_ring_requests': lab.calls.rings,
                                    'release_commands': lab.bridge.adapter.releases,
                                    'events': lab.bridge.adapter.status()['events']})
            finally:
                await lab.close()
    return {'run_at_utc': datetime.now(timezone.utc).isoformat(),
            'mode': 'offline_authenticated_loopback', 'upstream': 'controller_stub',
            'hardware_connected': False, 'microphone_opened': False,
            'accelerated_timing': '80 ms window in missed/slow scenarios; 80 ms post-release in normal scenario',
            'hub_relock_seconds_tested': 3, 'scenarios': results}
