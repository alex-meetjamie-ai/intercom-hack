#!/usr/bin/env python3
"""Real Opus/DTLS-SRTP in both directions, loopback only. NOT Access signalling."""
import asyncio
import fractions
import json
import math
import time
from array import array
from unittest.mock import patch
from aiortc import RTCPeerConnection, RTCConfiguration, AudioStreamTrack
from av import AudioFrame


class Tone(AudioStreamTrack):
    def __init__(self, frequency):
        super().__init__()
        self.frequency = frequency
        self.samples = 0
        self.start_time = None

    async def recv(self):
        if self.start_time is None:
            self.start_time = time.monotonic()
        await asyncio.sleep(max(0, self.start_time + self.samples / 48000 - time.monotonic()))
        count = 960
        samples = array('h', (int(4000 * math.sin(2 * math.pi * self.frequency * (self.samples + i) / 48000)) for i in range(count)))
        frame = AudioFrame(format='s16', layout='mono', samples=count)
        frame.planes[0].update(samples.tobytes())
        frame.sample_rate = 48000
        frame.pts = self.samples
        frame.time_base = fractions.Fraction(1, 48000)
        self.samples += count
        return frame


async def run():
    # aiortc normally gathers every NIC. Restrict this isolated harness to lo0;
    # this scoped patch never affects the reader or later office sessions.
    with patch('aioice.ice.get_host_addresses', return_value=['127.0.0.1']):
        peers = [RTCPeerConnection(RTCConfiguration(iceServers=[])) for _ in range(2)]
        received = [0, 0]
        energy = [0, 0]
        tasks = []
        async def consume(track, side):
            while True:
                frame = await track.recv()
                received[side] += 1
                energy[side] += sum(abs(x) for x in array('h', bytes(frame.planes[0])))
        for side, peer in enumerate(peers):
            @peer.on('track')
            def on_track(track, side=side):
                tasks.append(asyncio.create_task(consume(track, side)))
            peer.addTrack(Tone(440 if side == 0 else 660))
        try:
            await peers[0].setLocalDescription(await peers[0].createOffer())
            await peers[1].setRemoteDescription(peers[0].localDescription)
            await peers[1].setLocalDescription(await peers[1].createAnswer())
            await peers[0].setRemoteDescription(peers[1].localDescription)
            for _ in range(100):
                if min(received) >= 50:
                    break
                await asyncio.sleep(.1)
            assert min(received) >= 50, f'No two-way audio: {received}'
            assert min(energy) > 0, 'Decoded audio is silent'
            for peer in peers:
                assert peer.connectionState == 'connected'
                candidates = [l for l in peer.localDescription.sdp.splitlines() if l.startswith('a=candidate:')]
                assert candidates and all(' 127.0.0.1 ' in c for c in candidates), 'Non-loopback candidate'
            result = {'result': 'pass', 'transport': 'WebRTC Opus over DTLS-SRTP', 'network': 'loopback only',
                      'decoded_frames_in_each_direction': received,
                      'nonzero_audio_in_each_direction': [bool(e) for e in energy],
                      'unifi_access_signalling_tested': False, 'microphone_used': False}
            print(json.dumps(result, indent=2))
            return result
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.gather(*(peer.close() for peer in peers))


if __name__ == '__main__':
    asyncio.run(asyncio.wait_for(run(), timeout=30))
