"""Independent decoder checks plus local talkback and destination-scope checks."""
import asyncio
import struct
import unittest
from array import array
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import av
from aiortc.rtp import RtpPacket
from ems_media import EmsMedia, TestEncoder, tag


class EmsTests(unittest.IsolatedAsyncioTestCase):
    def reader(self, result=None):
        return SimpleNamespace(ip='127.0.0.1', controller='127.0.0.1', event=lambda *a, **k: None,
                               calls=SimpleNamespace(request=AsyncMock(return_value=result),
                                                     provisioned=lambda: {'origin': 'https://127.0.0.1:12443'}))

    def test_generated_codecs_decode(self):
        enc = TestEncoder()
        video = av.CodecContext.create('h264', 'r')
        opus = av.CodecContext.create('opus', 'r')
        opus.extradata = enc.opus.extradata
        aac = av.CodecContext.create('aac', 'r')
        aac.extradata = enc.aac.extradata
        counts, energy = {8: 0, 10: 0}, {8: 0., 10: 0.}
        resamplers = {k: av.AudioResampler(format='s16', layout='mono', rate=48000) for k in counts}
        for packet in enc.video_packet():
            frames = video.decode(av.Packet(bytes(packet)))
            self.assertEqual((frames[0].width, frames[0].height), (640, 360))
        for _ in range(10):
            for kind, packet in enc.audio_packets():
                for frame in (aac if kind == 8 else opus).decode(av.Packet(bytes(packet))):
                    counts[kind] += 1
                    for pcm in resamplers[kind].resample(frame):
                        energy[kind] += sum(abs(v) for v in array('h', bytes(pcm.planes[0])[:pcm.samples * 2]))
        self.assertTrue(all(n >= 5 for n in counts.values()))
        self.assertTrue(all(e > 0 for e in energy.values()))

    async def test_initial_stream_uses_firmware_opus_tag_ten(self):
        result = {'ip': '127.0.0.1', 'port': 7550,
                  'streamHei': 'lab-high', 'streamMid': 'lab-mid', 'streamLow': 'lab-low'}
        media = EmsMedia(self.reader(result))
        buffers = []
        class Sink:
            def __init__(self): self.data = bytearray(); buffers.append(self.data)
            def write(self, data): self.data.extend(data)
            async def drain(self): pass
            def close(self): pass
            async def wait_closed(self): pass
        async def connect(*args):
            return asyncio.StreamReader(), Sink()
        try:
            with patch('asyncio.open_connection', side_effect=connect), patch.object(media, 'listen_talkback', new_callable=AsyncMock):
                await media.start()
                await asyncio.sleep(.08)
            for data in buffers:
                pos, tags = 13, []
                while pos < len(data):
                    kind, length = data[pos], int.from_bytes(data[pos+1:pos+4], 'big')
                    payload = bytes(data[pos+11:pos+11+length])
                    tags.append((kind, payload))
                    pos += 11 + length + 4 + 16
                self.assertEqual(pos, len(data))
                # Independent wire evidence: G3 gj.b.n(true) returns decimal 10.
                self.assertIn((10, b'\xcf\x00\x03\x00'), tags)
                self.assertTrue(any(k == 10 and p != b'\xcf\x00\x03\x00' for k, p in tags))
                self.assertNotIn(11, [k for k, _ in tags])
        finally:
            await media.close()

    def test_extended_frame_layout(self):
        data = tag(10, b'example', 0x12345678, 48000, 960)
        self.assertEqual(data[:4], b'\x0a\x00\x00\x07')
        self.assertEqual(data[4:8], b'\x34\x56\x78\x12')
        self.assertEqual(struct.unpack('>I', data[18:22])[0], 18)
        self.assertEqual(struct.unpack('>IIQ', data[22:]), (48000, 0, 960))
        with self.assertRaises(ValueError):
            tag(8, b'x', -1)

    async def test_ingest_rejects_other_host_before_opening_sockets(self):
        media = EmsMedia(self.reader({'ip': '203.0.113.1', 'port': 7550}))
        with patch('asyncio.open_connection', new_callable=AsyncMock) as connect:
            with self.assertRaises(ValueError):
                await media.start()
            connect.assert_not_awaited()
        self.assertFalse(media.receivers)

    async def test_real_udp_talkback_decode_and_source_filter(self):
        media = EmsMedia(self.reader())
        transport = None
        try:
            await media.listen_talkback()
            enc = TestEncoder()
            packets = [p for kind, p in enc.audio_packets() if kind == 10]
            packet = RtpPacket(payload_type=111, sequence_number=1, timestamp=0, ssrc=123)
            packet.payload = bytes(packets[0])
            data = packet.serialize()
            media.receivers[0].get_protocol().datagram_received(data, ('203.0.113.1', 3333))
            self.assertEqual(media.talkback_packets, 0)
            transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
                asyncio.DatagramProtocol, remote_addr=('127.0.0.1', 8181))
            transport.sendto(data)
            for _ in range(20):
                if media.talkback_frames:
                    break
                await asyncio.sleep(.01)
            self.assertEqual(media.talkback_packets, 1)
            self.assertGreater(media.talkback_frames, 0)
            self.assertTrue(media.talkback_nonzero)
        finally:
            if transport:
                transport.close()
            await media.close()

    async def test_decoded_talkback_reaches_audio_output_only_while_answered(self):
        from audio_io import MacAudio, SAMPLES, SILENCE
        from test_audio_io import FakeDevices
        devices = FakeDevices()
        audio = MacAudio(0, 1, backend=devices)
        media = EmsMedia(self.reader())
        media.audio = audio
        try:
            audio.start()
            await media.listen_talkback()
            receiver = media.receivers[0].get_protocol()
            enc = TestEncoder()
            def receive(seq, host='127.0.0.1'):
                packet = RtpPacket(payload_type=111, sequence_number=seq, timestamp=seq * 960, ssrc=123)
                packet.payload = bytes(next(p for k, p in enc.audio_packets() if k == 10))
                receiver.datagram_received(packet.serialize(), (host, 1234))
            out = bytearray(len(SILENCE))
            receive(1)
            devices.streams[0].options['callback'](out, SAMPLES, None, False)
            self.assertEqual(bytes(out), SILENCE)
            audio.set_active(True)
            receive(2, '203.0.113.1')
            devices.streams[0].options['callback'](out, SAMPLES, None, False)
            self.assertEqual(bytes(out), SILENCE)
            receive(2)
            devices.streams[0].options['callback'](out, SAMPLES, None, False)
            self.assertNotEqual(bytes(out), SILENCE)
            frames = media.talkback_frames
            empty = RtpPacket(payload_type=111, sequence_number=3, timestamp=1920, ssrc=123)
            receiver.datagram_received(empty.serialize(), ('127.0.0.1', 1234))
            self.assertEqual(media.talkback_empty_packets, 1)
            receive(2)  # A repeated sequence number must not poison the decoder.
            self.assertGreater(media.talkback_frames, frames)
            self.assertEqual(media.talkback_errors, {})
            devices.streams[0].options['callback'](out, SAMPLES, None, False)
            self.assertNotEqual(bytes(out), SILENCE)
            receive(3)
            audio.set_active(False)
            devices.streams[0].options['callback'](out, SAMPLES, None, False)
            self.assertEqual(bytes(out), SILENCE)
        finally:
            await media.close()
            audio.close()


if __name__ == '__main__':
    unittest.main()
