"""Experimental Access EMS ingest: generated H.264/AAC/Opus over local TCP.

Wire format comes from G3 firmware EmsManager, kj.y and gj.b/c. The default is
generated media; an explicitly supplied PCM backend enables real audio.
No camera, SKS bus or lock is opened. Stream names are private credentials.
"""
import argparse
import asyncio
import contextlib
import json
import math
import re
import struct
import time
from array import array
from fractions import Fraction

import av
from aiortc.rtp import RtpPacket


def settings():
    audio = [{'bindPort': port, 'bitsPerSample': 16, 'channels': 1,
              'samplingRate': 48000, 'typeFmt': codec}
             for port, codec in ((8182, 'aac'), (8181, 'opus'))]
    return {'videoCodec': 'h264', 'aacPort': '8182', 'opusPort': '8181',
            'channels': ['low', 'mid', 'hei'], 'talkbackSettings': audio[0],
            'audioSettings': audio,
            'channelSettings': [{'id': i, 'width': 640, 'height': 360, 'fps': 15,
                                 'bitrate': 200000, 'quality': q, 'fpsValues': [15]}
                                for i, q in enumerate(('high', 'medium', 'low'))]}


def amf(value):
    if isinstance(value, bool):
        return b'\x01' + bytes([value])
    if isinstance(value, (int, float)):
        return b'\x00' + struct.pack('>d', value)
    if isinstance(value, str):
        b = value.encode()
        if len(b) > 65535:
            raise ValueError('AMF string too long')
        return b'\x02' + struct.pack('>H', len(b)) + b
    if isinstance(value, dict):
        return b'\x03' + b''.join(struct.pack('>H', len(k.encode())) + k.encode() + amf(v)
                                 for k, v in value.items()) + b'\x00\x00\x09'
    raise ValueError('Unsupported AMF value')


def tag(kind, payload, ms=0, rate=None, ticks=0):
    if not 0 <= ms < 2**32 or len(payload) >= 2**24:
        raise ValueError('Invalid EMS frame')
    head = bytes([kind]) + len(payload).to_bytes(3, 'big')
    head += (ms & 0xffffff).to_bytes(3, 'big') + bytes([ms >> 24]) + b'\x00' * 3
    result = head + payload + struct.pack('>I', 11 + len(payload))
    if rate is not None:
        result += struct.pack('>IIQ', rate, 0, ticks)
    return result


def script(name, values, ms=0):
    return tag(18, amf(name) + amf(values), ms, 1000, ms)


def nal_units(packet):
    return [n for n in re.split(b'\x00\x00(?:\x00)?\x01', bytes(packet)) if n]


def avcc(sps, pps):
    return (b'\x01' + sps[1:4] + b'\xff\xe1' + struct.pack('>H', len(sps)) + sps
            + b'\x01' + struct.pack('>H', len(pps)) + pps)


class TestEncoder:
    def __init__(self):
        self.video = av.CodecContext.create('libx264', 'w')
        self.video.width, self.video.height = 640, 360
        self.video.pix_fmt = 'yuv420p'
        self.video.time_base, self.video.framerate = Fraction(1, 15), Fraction(15, 1)
        self.video.thread_count = 1
        self.video.options = {'preset': 'ultrafast', 'tune': 'zerolatency',
                              'x264-params': 'keyint=15:min-keyint=15:scenecut=0:repeat-headers=1:slices=1'}
        self.video.open()
        self.opus = av.CodecContext.create('libopus', 'w')
        self.opus.sample_rate, self.opus.layout, self.opus.format = 48000, 'mono', 's16'
        self.opus.time_base, self.opus.bit_rate = Fraction(1, 48000), 64000
        self.opus.options = {'frame_duration': '20', 'application': 'lowdelay'}
        self.opus.open()
        self.aac = av.CodecContext.create('aac', 'w')
        self.aac.sample_rate, self.aac.layout, self.aac.format = 48000, 'mono', 'fltp'
        self.aac.time_base, self.aac.bit_rate = Fraction(1, 48000), 64000
        self.aac.open()
        self.resampler = av.AudioResampler(format='fltp', layout='mono', rate=48000)
        self.samples = self.frames = 0

    def video_packet(self):
        frame = av.VideoFrame(640, 360, 'yuv420p')
        # A moving luma stripe makes a stalled image visible without a camera.
        for i, plane in enumerate(frame.planes):
            plane.update(bytes([40 if i == 0 else 128]) * plane.buffer_size)
        data = bytearray(bytes(frame.planes[0]))
        x = (self.frames * 8) % 608
        for y in range(150, 210):
            start = y * frame.planes[0].line_size + x
            data[start:start + 32] = b'\xd0' * 32
        frame.planes[0].update(data)
        frame.pts, frame.time_base = self.frames, Fraction(1, 15)
        self.frames += 1
        return self.video.encode(frame)

    def audio_packets(self, pcm=None):
        frame = av.AudioFrame(format='s16', layout='mono', samples=960)
        if pcm is None:
            pcm = array('h', (int(3000 * math.sin(2 * math.pi * 440 * (self.samples + i) / 48000))
                              for i in range(960))).tobytes()
        if not isinstance(pcm, bytes) or len(pcm) != 1920:
            raise ValueError('Audio requires exactly 20 ms of s16 mono 48 kHz PCM')
        frame.planes[0].update(pcm)
        frame.sample_rate, frame.pts, frame.time_base = 48000, self.samples, Fraction(1, 48000)
        self.samples += 960
        # G3 gj.b.n(true) uses vendor FLV tag 10 for both Opus config and data.
        result = [(10, p) for p in self.opus.encode(frame)]
        for f in self.resampler.resample(frame):
            result += [(8, p) for p in self.aac.encode(f)]
        return result


class EmsMedia:
    def __init__(self, reader):
        self.reader = reader
        self.writers, self.tasks = [], []
        self.feedback = 0
        self.sent = 0
        self.running = False
        self.receivers = []
        self.talkback_packets = self.talkback_frames = 0
        self.talkback_errors = {}
        self.talkback_empty_packets = 0
        self.talkback_nonzero = False
        self.audio = None
        self.playback_codec = None

    def status(self):
        return {'running': self.running, 'sent_bytes': self.sent, 'feedback_messages': self.feedback,
                'talkback_packets': self.talkback_packets, 'talkback_frames': self.talkback_frames,
                'talkback_errors': dict(self.talkback_errors),
                'talkback_empty_packets': self.talkback_empty_packets,
                'talkback_nonzero': self.talkback_nonzero,
                'source': self.audio.source if self.audio else 'generated_media',
                'audio': self.audio.status() if self.audio else None}

    async def listen_talkback(self):
        media = self
        class Receiver(asyncio.DatagramProtocol):
            def __init__(self, codec):
                self.codec = codec
                self.decoder = av.CodecContext.create(codec, 'r')
                if codec == 'opus':
                    self.decoder.extradata = b'OpusHead\x01\x01\x00\x00\x80\xbb\x00\x00\x00\x00\x00'
                self.resampler = av.AudioResampler(format='s16', layout='mono', rate=48000)

            def datagram_received(self, data, addr):
                if addr[0] != media.reader.controller or not 1 <= len(data) <= 8192:
                    return
                media.talkback_packets += 1
                stage = 'framing'
                try:
                    if self.codec == 'opus':
                        packet = RtpPacket.parse(data)
                        # No sequence-based rejection in this diagnostic path.
                        # Source scope and decoded PCM bounds still apply.
                        payload = packet.payload
                    else:
                        # Reader AAC receiver strips a leading 4-byte SSRC when
                        # its first byte is zero, then consumes ADTS frames.
                        payload = data[4:] if data[0] == 0 else data
                    # An empty packet drains a PyAV decoder into EOF. Native
                    # talkback can send empty RTP; it is not an end-of-stream.
                    if not payload:
                        media.talkback_empty_packets += 1
                        return
                    stage = 'decode'
                    for f in self.decoder.decode(av.Packet(payload)):
                        media.talkback_frames += 1
                        stage = 'resample'
                        for pcm in self.resampler.resample(f):
                            data_pcm = bytes(pcm.planes[0])[:pcm.samples * 2]
                            media.talkback_nonzero |= any(array('h', data_pcm))
                            if media.audio and hasattr(media.audio, 'record_incoming'):
                                # Explicit diagnostics can capture incoming audio
                                # even when a receiver's pickup signal is missing.
                                media.audio.record_incoming(data_pcm, 'ems')
                            if media.audio and media.audio.active:
                                # A receiver can send both codecs. Select one per
                                # active conversation, rather than playing twice.
                                if media.playback_codec is None:
                                    media.playback_codec = self.codec
                                if media.playback_codec == self.codec:
                                    media.audio.write_pcm(data_pcm)
                            else:
                                media.playback_codec = None
                    if media.talkback_frames >= 50 and not getattr(self, 'reported', False):
                        self.reported = True
                        media.reader.event('ems_talkback_decoded', codec=self.codec,
                                           frames=media.talkback_frames, nonzero=media.talkback_nonzero)
                except (ValueError, av.FFmpegError) as exc:
                    key = self.codec + ':' + stage + ':' + type(exc).__name__
                    count = media.talkback_errors.get(key, 0) + 1
                    media.talkback_errors[key] = count
                    if count <= 3:
                        media.reader.event('ems_talkback_decode_failed', codec=self.codec,
                                           stage=stage, error_type=type(exc).__name__,
                                           bytes=len(data), count=count)
        for port, codec in ((8181, 'opus'), (8182, 'aac')):
            transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
                lambda codec=codec: Receiver(codec), local_addr=(self.reader.ip, port))
            self.receivers.append(transport)

    async def consume_feedback(self, source):
        try:
            while True:
                kind, length = struct.unpack('>HH', await source.readexactly(4))
                await source.readexactly(length)
                self.feedback += 1
                if self.feedback == 1:
                    self.reader.event('ems_feedback_received', kind=kind, bytes=length)
        except (asyncio.IncompleteReadError, OSError):
            self.reader.event('ems_ingest_closed')
            if self.audio:
                self.audio.set_active(False)
                self.reader.call_lifecycle('transport_failed')

    async def broadcast(self, data):
        for writer in self.writers:
            writer.write(data)
        await asyncio.gather(*(asyncio.wait_for(w.drain(), 3) for w in self.writers))
        self.sent += len(data) * len(self.writers)

    async def start(self):
        result = await self.reader.calls.request('POST', self.reader.calls.provisioned()['origin'] +
                                                '/api/v2/ms/ingest_point', settings())
        if result.get('ip') != self.reader.controller or result.get('port') != 7550:
            raise ValueError('EMS target is outside the selected controller ingest port')
        names = [result.get(k) for k in ('streamHei', 'streamMid', 'streamLow')]
        if any(not isinstance(n, str) or not 0 < len(n) <= 1024 for n in names):
            raise ValueError('Missing EMS stream credentials')
        await self.listen_talkback()
        encoder = TestEncoder()
        packets = encoder.video_packet()
        nals = nal_units(packets[0])
        sps = next(n for n in nals if n[0] & 31 == 7)
        pps = next(n for n in nals if n[0] & 31 == 8)
        for name in names:
            source, writer = await asyncio.wait_for(asyncio.open_connection(self.reader.controller, 7550), 3)
            self.writers.append(writer)
            self.tasks.append(asyncio.create_task(self.consume_feedback(source)))
            meta = {'audioBandwidth': 768000, 'audioChannels': 1, 'audioFrequency': 48000,
                    'channelId': 0, 'extendedFormat': True, 'hasAudio': True, 'hasVideo': True,
                    'streamName': name, 'videoBandwidth': 200000, 'videoFps': 15,
                    'videoWidth': 640, 'videoHeight': 360}
            writer.write(b'FLV\x01\x07\x00\x00\x00\x09\x00\x00\x00\x00' + script('onMetaData', meta))
        await self.broadcast(tag(9, b'\x17\x00\x00\x00\x00' + avcc(sps, pps), rate=90000))
        await self.broadcast(tag(8, b'\xaf\x00' + encoder.aac.extradata[:2], rate=48000))
        await self.broadcast(tag(10, b'\xcf\x00\x03\x00', rate=90000))
        self.reader.event('ems_ingest_connected', streams=len(self.writers),
                          source=self.audio.source if self.audio else 'generated_media')
        self.running = True
        self.tasks.append(asyncio.create_task(self.send(encoder, packets)))

    async def send_video(self, packet):
        ticks = max(0, round(packet.pts * packet.time_base * 90000))
        ms = ticks // 90
        nals = [n for n in nal_units(packet) if n[0] & 31 in (1, 5)]
        if packet.is_keyframe:
            await self.broadcast(script('onClockSync', {'streamClock': ms, 'streamClockBase': 0,
                                                        'wallClock': int(time.time() * 1000)}, ms))
        payload = bytes([0x17 if packet.is_keyframe else 0x27]) + b'\x01\x00\x00\x00'
        payload += b''.join(struct.pack('>I', len(n)) + n for n in nals)
        await self.broadcast(tag(9, payload, ms, 90000, ticks))

    async def send(self, encoder, first_packets):
        try:
            start = time.monotonic()
            for packet in first_packets:
                await self.send_video(packet)
            while True:
                await asyncio.sleep(max(0, start + encoder.samples / 48000 - time.monotonic()))
                if encoder.frames / 15 <= encoder.samples / 48000:
                    for packet in encoder.video_packet():
                        await self.send_video(packet)
                pcm = self.audio.read_pcm() if self.audio else None
                for kind, packet in encoder.audio_packets(pcm):
                    ticks = max(0, packet.pts)
                    payload = (b'\xaf\x01' if kind == 8 else b'') + bytes(packet)
                    await self.broadcast(tag(kind, payload, ticks // 48, 48000, ticks))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.reader.event('ems_send_failed', error_type=type(exc).__name__)
            if self.audio:
                self.audio.set_active(False)
                self.reader.call_lifecycle('transport_failed')
        finally:
            self.running = False

    async def close(self):
        if self.audio:
            self.audio.set_active(False)
        for transport in self.receivers:
            transport.close()
        self.receivers.clear()
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        for w in self.writers:
            w.close()
            with contextlib.suppress(OSError):
                await w.wait_closed()
        self.writers.clear()
        self.running = False


async def run(args):
    from poc import office_identity, OFFICE_IP
    from reader import Reader
    r = Reader(args.state, ip=office_identity(), controller=OFFICE_IP, lab=False)
    media = EmsMedia(r)
    try:
        await media.start()
        await asyncio.sleep(args.seconds)
    finally:
        await media.close()
        await r.calls.close()
        print(json.dumps(media.status()), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    parser.add_argument('--seconds', type=int, choices=range(1, 301), default=60, metavar='1..300')
    try:
        asyncio.run(run(parser.parse_args()))
    except KeyboardInterrupt:
        pass
