"""Experimental UA-Hub: virtual relay only, no GPIO or physical door connection.

Profile and RPC fields: official UAH 4.13.4 and Access 4.3.12 device definition.
This module must never be connected to a hardware relay without a separate design.
"""
import argparse
import asyncio
import base64
import copy
import json
import re
import signal
import struct
import uuid
from pathlib import Path

import provisioning
import wire
from reader import Reader
from security import private_write, save_state

MODEL = 'UAH'
GUID = '4a5e238f-4bae-48d5-84d7-dd2b0e919ab5'
FW = 'DA.mt7621.v4.13.4.0.g2aa3fc0.260815.0818'
NAME = 'Software Hub PoC'


class VirtualLinkedReader(Reader):
    """Report the locally simulated hub, never an association to physical hardware."""
    hub_id = None

    def info(self):
        result = super().info()
        if self.hub_id:
            result['attrs']['uah_id'] = self.hub_id
        return result

    def device_stat(self):
        result = super().device_stat()
        # G3 LocalMqttService includes uah_id when its local hub is known.
        if self.hub_id:
            result += wire.field(4, 'uah_id=' + self.hub_id)
        return result

    def associate_virtual_hub(self, hub):
        if (not isinstance(hub, VirtualHub) or hub.reader_id != self.state['id']
                or hub.ip != self.ip or hub.controller != self.controller):
            raise ValueError('Only a matching, co-located simulated hub is supported')
        self.hub_id = hub.state['id']


class VirtualHub(Reader):
    def __init__(self, *args, reader_id, **kwargs):
        super().__init__(*args, **kwargs)
        if not re.fullmatch(r'02[0-9a-f]{10}', reader_id) or reader_id == self.state['id']:
            raise ValueError('Expected a distinct synthetic reader identity')
        if self.state.get('adoption') and self.state.get('poc_role') != 'virtual_hub':
            raise ValueError('Refusing to use an adopted non-hub state')
        self.state['poc_role'] = 'virtual_hub'
        save_state(self.folder, self.state)
        self.reader_id = reader_id
        self.relay_unlocked = False
        self.unlock_count = 0
        self.relock_handle = None
        self.unlock_adapter = None
        self.linked_bridge = None

    def call_lifecycle(self, action):
        if action == 'transport_failed' and self.linked_bridge:
            self.linked_bridge.native_event(action)
        return super().call_lifecycle(action)

    def info(self):
        result = super().info()
        result.update(model=MODEL, name=(self.state.get('adoption') or {}).get('name', NAME))
        result['attrs'].update(fw=FW, guid=GUID, port=str(self.port), **self.virtual_attrs())
        return result

    def virtual_attrs(self):
        mac = ':'.join(self.reader_id[i:i+2] for i in range(0, 12, 2))
        return {'port-mac-port2': mac,
                'input_state_rly-lock_dry': 'on' if self.relay_unlocked else 'off',
                'input_state_dps': 'off', 'input_state_EMERGY': 'off',
                'input_state_SW-EMERGY': 'off'}

    def device_stat(self):
        base = wire.protobuf(super().device_stat())
        attrs = dict(v.decode().split('=', 1) for k, v in base if k == 4)
        attrs.update(self.virtual_attrs(), fw=FW, guid=GUID, port=str(self.port))
        # A hub has no reader's fingerprint capability bit.
        attrs.pop('device_capability', None)
        return (wire.field(1, self.state['id']) + wire.field(2, MODEL)
                + wire.field(3, self.info()['name'])
                + b''.join(wire.field(4, f'{k}={v}') for k, v in attrs.items()))

    def discovery_packet(self):
        _, _, fields = wire.parse_tlv(super().discovery_packet())
        fields.update({3: FW.encode(), 11: NAME.encode(), 12: MODEL.encode(), 21: MODEL.encode(),
                       22: b'v4.13.4', 36: struct.pack('!I', self.port), 43: uuid.UUID(GUID).bytes})
        return wire.tlv_packet(fields)

    def diagnostics(self):
        return {'virtual_hub': {'relay': 'unlocked' if self.relay_unlocked else 'locked',
                                'unlock_commands': self.unlock_count, 'physical_actuation': False}}

    def input_state(self):
        # UAH InputService sends models.InputState inside a ProtoMessage on
        # /input/state. These names omit the device-stat "input_state_" prefix.
        states = {'ren': False, 'rex': False, 'dps': False, 'rel': False,
                  'rly-lock_dry': self.relay_unlocked,
                  'EMERGY': False, 'SW-EMERGY': False}
        return b''.join(wire.field(1, wire.field(1, name) + b'\x10' + wire.varint(int(value)))
                        for name, value in states.items())

    def publish_stat(self):
        super().publish_stat()
        if self.mqtt_client and self.mqtt_client.is_connected():
            self.mqtt_client.publish(self.resource() + '/input/state',
                                     wire.message({}, self.input_state()), qos=0, retain=False)
            self.event('input_state_sent', relay='unlocked' if self.relay_unlocked else 'locked')

    def relock(self):
        self.relay_unlocked = False
        if self.unlock_adapter:
            self.unlock_adapter.relock()
        self.relock_handle = None
        self.event('virtual_relay_locked', physical_actuation=False)
        self.publish_stat()

    def apply_hub_config(self, body):
        fields = wire.protobuf(body)
        singular = {}
        for tag, value in fields:
            if tag in (1, 10, 13):
                if tag in singular or not isinstance(value, int):
                    raise ValueError('Invalid hub configuration')
                singular[tag] = value
        if 1 not in singular or singular.get(13):
            raise ValueError('Missing revision or unsupported external config')
        if singular[1] < self.state.get('provisioning', {}).get('revision', 0) and not singular.get(10):
            raise ValueError('Stale hub configuration')
        pairs = [provisioning.decode('Config', value) for tag, value in fields if tag == 2]
        state = copy.deepcopy(self.state)
        state.setdefault('settings', {}).update(provisioning.config_pairs(pairs))
        state['provisioning'] = {'revision': singular[1], 'wire_base64': base64.b64encode(body).decode()}
        save_state(self.folder, state)
        self.state = state

    def rpc_reply(self, topic, packet):
        # Reuse strict topic scope and envelope validation before custom operations.
        meta, body = wire.parse_message(packet)
        path = meta.get('path', '')
        if path not in ('/config/update', '/relay/unlock'):
            return super().rpc_reply(topic, packet)
        reply_topic, _ = super().rpc_reply(topic, packet)
        code, error, response = 0, '', b'success'
        try:
            if path == '/config/update':
                self.apply_hub_config(body)
                self.event('hub_configuration_applied', revision=self.state['provisioning']['revision'])
                self.publish_stat()
            else:
                entries = wire.protobuf(body)
                if len({t for t, _ in entries}) != len(entries):
                    raise ValueError('Duplicate unlock field')
                data = dict(entries)
                if not isinstance(data.get(1), bytes) or not 0 < len(data[1]) <= 256:
                    raise ValueError('Missing requesting user')
                if data.get(2, 0) or data.get(3, 0) or data.get(6, 0) not in (0, 1) or 11 in data:
                    raise ValueError('Only the single virtual door is supported')
                if 7 in data and data[7] not in (b'', self.reader_id.encode(), self.state['id'].encode()):
                    raise ValueError('Unlock device outside PoC')
                if self.unlock_adapter and not self.unlock_adapter.release(meta.get('requestId', '')):
                    # An acknowledged retry must not generate a second pulse or
                    # extend the first one. The RPC reply remains successful.
                    return reply_topic, wire.message({'path': path, 'requestId': meta.get('requestId', ''),
                                                       'code': '0', 'error': ''}, b'success')
                self.relay_unlocked = True
                self.unlock_count += 1
                if self.relock_handle:
                    self.relock_handle.cancel()
                self.relock_handle = asyncio.get_running_loop().call_later(3, self.relock)
                self.event('virtual_relay_unlocked', command_number=self.unlock_count, physical_actuation=False)
                self.publish_stat()
        except (ValueError, UnicodeError, TypeError):
            code, error, response = 1, 'Unsupported or malformed virtual hub operation', b''
            self.event('virtual_hub_operation_rejected', operation=path)
        return reply_topic, wire.message({'path': path, 'requestId': meta.get('requestId', ''),
                                         'code': str(code), 'error': error}, response)

    async def close(self):
        if self.relock_handle:
            self.relock_handle.cancel()
        self.relay_unlocked = False
        await super().close()


async def main(args):
    from poc import OFFICE_IP, office_identity, preflight
    if not 0 < args.minutes <= 120:
        raise ValueError('Invalid runtime limit')
    if args.audio == 'mac' and (not args.ems or not args.sks_sim):
        raise ValueError('--audio mac requires --ems and --sks-sim')
    if args.sks_sim and not args.ems:
        raise ValueError('--sks-sim requires --ems for the call/audio test')
    if args.audio == 'mac' and (args.input_device is None or args.output_device is None):
        raise ValueError('Select input and headphone output with --input-device and --output-device')
    ip = office_identity()
    status = await preflight(ip)
    if status['12812'] != 'reachable' or status['12443'] != 'reachable':
        raise ValueError('Access is not reachable')
    reader = VirtualLinkedReader(args.reader_state, ip=ip, controller=OFFICE_IP, lab=False)
    if not reader.state.get('adoption'):
        raise ValueError('Use the already adopted software reader')
    hub = VirtualHub(args.state, ip=ip, controller=OFFICE_IP, port=8081, lab=False,
                     reader_id=reader.state['id'])
    reader.associate_virtual_hub(hub)
    audio = None
    try:
        if args.sks_sim:
            from audio_io import ToneAudio, MacAudio
            from sks_bridge import SksBridge
            audio = (MacAudio(args.input_device, args.output_device, args.output_gain)
                     if args.audio == 'mac' else ToneAudio())
            SksBridge(reader, hub, audio, window=args.sks_window, after_release=args.sks_after_release)
            audio.start()
        await reader.start_http()
        await reader.start_control()
        await hub.start_http()
        await hub.start_control()
        # One discovery listener advertises the new hub; the existing reader reconnects over MQTT.
        await hub.start_discovery()
        if args.ems:
            await reader.ems.start()
        print('Virtual hub has no physical outputs. Unlock commands relock after 3 seconds.', flush=True)
        if reader.bridge:
            print('SKS simulation: ring opens a bounded unlock window; answer enables audio; hangup mutes it.', flush=True)
        done = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig, done.set)
        try:
            await asyncio.wait_for(done.wait(), args.minutes * 60)
        except asyncio.TimeoutError:
            pass
    finally:
        await reader.close()
        await hub.close()
        if audio:
            audio.close()
        print('Stopped virtual hub and reader.', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state', default='.state-office-hub')
    p.add_argument('--reader-state', default='.state-office-access-v3')
    p.add_argument('--minutes', type=float, default=20)
    p.add_argument('--ems', action='store_true')
    p.add_argument('--sks-sim', action='store_true', help='Enable simulated SKS call window and audio gating')
    p.add_argument('--sks-window', type=float, default=120, help='Simulated post-ring window, 0 < seconds <= 150')
    p.add_argument('--sks-after-release', type=float, default=10,
                   help='End an answered simulated call this many seconds after release, capped by its original window')
    p.add_argument('--audio', choices=('tone', 'mac'), default='tone')
    p.add_argument('--input-device', type=int)
    p.add_argument('--output-device', type=int, help='Explicit headphone device ID; no echo cancellation')
    p.add_argument('--output-gain', type=float, default=.35)
    asyncio.run(main(p.parse_args()))
