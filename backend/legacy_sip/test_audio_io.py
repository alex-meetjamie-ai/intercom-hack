import math
import tempfile
import wave
import unittest
from array import array
from pathlib import Path

import av
from audio_io import MacAudio, PcmPipe, RATE, SAMPLES, SILENCE
from ems_media import TestEncoder
from audio_recording import DiagnosticRecording


class FakeStream:
    def __init__(self, **kwargs):
        self.options = kwargs
        self.active = self.closed = False

    def start(self):
        self.active = True

    def abort(self):
        self.active = False

    def close(self):
        self.closed = True


class FakeDevices:
    def __init__(self):
        self.streams = []

    def check_input_settings(self, **kwargs):
        pass

    def check_output_settings(self, **kwargs):
        pass

    def RawInputStream(self, **kwargs):
        stream = FakeStream(**kwargs)
        self.streams.append(stream)
        return stream

    RawOutputStream = RawInputStream


class AudioTests(unittest.TestCase):
    def test_recording_is_bounded_private_and_distinguishes_missing_audio(self):
        now = [0.0]
        recording = DiagnosticRecording(1, clock=lambda: now[0])
        recording.add('microphone', b'\x02\x00' * 100000)
        now[0] = 1.1
        recording.add('incoming_ems', b'\x03\x00' * 960)
        with tempfile.TemporaryDirectory() as folder:
            result = recording.finish(folder)['recordings']
            self.assertEqual(result['microphone']['samples'], 48000)
            self.assertIsNone(result['incoming_ems']['path'])
            path = Path(result['microphone']['path'])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with wave.open(str(path)) as f:
                self.assertEqual((f.getframerate(), f.getnchannels(), f.getsampwidth(), f.getnframes()),
                                 (48000, 1, 2, 48000))
            self.assertFalse(recording.active)
        for seconds in (0, 31, True, 1.5):
            with self.assertRaises(ValueError):
                DiagnosticRecording(seconds)

    def test_pcm_bounds_mute_and_stale_audio(self):
        now = [1.0]
        pipe = PcmPipe(clock=lambda: now[0])
        pipe.push(b'\x01\x00' * SAMPLES)
        self.assertEqual(pipe.read(len(SILENCE)), SILENCE)
        pipe.enable(True)
        for i in range(12):
            pipe.push(bytes([i, 0]) * SAMPLES)
        self.assertEqual(len(pipe.data), pipe.capacity)
        self.assertEqual(pipe.dropped_bytes, 2 * len(SILENCE))
        self.assertEqual(pipe.read(len(SILENCE)), b'\x02\x00' * SAMPLES)
        now[0] += .26
        self.assertEqual(pipe.read(len(SILENCE)), SILENCE)
        pipe.push(b'\x03\x00' * SAMPLES)
        pipe.enable(False)
        pipe.enable(True)
        self.assertEqual(pipe.read(len(SILENCE)), SILENCE)

    def test_explicit_devices_callback_bridge_and_no_idle_capture(self):
        devices = FakeDevices()
        audio = MacAudio(2, 4, output_gain=.5, backend=devices)
        self.assertEqual(devices.streams, [])
        try:
            audio.start()
            output, input_ = devices.streams
            self.assertEqual(output.options['device'], 4)
            self.assertEqual(input_.options['device'], 2)
            pcm = array('h', [2000] * SAMPLES).tobytes()
            input_.options['callback'](pcm, SAMPLES, None, False)
            self.assertEqual(audio.read_pcm(), SILENCE)
            audio.set_active(True)
            input_.options['callback'](pcm, SAMPLES, None, False)
            self.assertEqual(audio.read_pcm(), pcm)
            self.assertEqual(audio.read_pcm('webrtc'), pcm)
            audio.write_pcm(pcm)
            audio.write_pcm(pcm, route='webrtc')  # No duplicate playback via two transports.
            out = bytearray(len(pcm))
            output.options['callback'](out, SAMPLES, None, False)
            self.assertEqual(array('h', out), array('h', [1000] * SAMPLES))
            output.options['callback'](out, SAMPLES, None, False)
            self.assertEqual(bytes(out), SILENCE)
            audio.write_pcm(pcm)
            audio.set_active(False)
            audio.set_active(True)
            output.options['callback'](out, SAMPLES, None, False)
            self.assertEqual(bytes(out), SILENCE)
        finally:
            audio.close()
        self.assertTrue(all(s.closed and not s.active for s in devices.streams))
        self.assertFalse(audio.status()['microphone_open'])

    def test_partial_open_failure_cleans_up_and_device_loss_does_not_fallback(self):
        devices = FakeDevices()
        def failed_input(**kwargs):
            raise RuntimeError('input unavailable')
        devices.RawInputStream = failed_input
        audio = MacAudio(0, 1, backend=devices)
        with self.assertRaises(RuntimeError):
            audio.start()
        self.assertTrue(devices.streams[0].closed)
        self.assertEqual(audio.streams, [])
        devices = FakeDevices()
        audio = MacAudio(0, 1, backend=devices)
        try:
            audio.start()
            audio.set_active(True)
            devices.streams[1].active = False
            with self.assertRaises(RuntimeError):
                audio.read_pcm()
            self.assertFalse(audio.active)
            self.assertTrue(audio.faulted)
        finally:
            audio.close()

    def test_selected_pcm_is_encoded_instead_of_the_test_tone(self):
        encoder = TestEncoder()
        decoder = av.CodecContext.create('opus', 'r')
        decoder.extradata = encoder.opus.extradata
        resampler = av.AudioResampler(format='s16', layout='mono', rate=RATE)
        received = []
        for j in range(12):
            pcm = array('h', (int(8000 * math.sin(2 * math.pi * 1000 * (j * SAMPLES + i) / RATE))
                              for i in range(SAMPLES))).tobytes()
            for kind, packet in encoder.audio_packets(pcm):
                if kind == 10:
                    for frame in decoder.decode(av.Packet(bytes(packet))):
                        for f in resampler.resample(frame):
                            received.extend(array('h', bytes(f.planes[0])[:f.samples * 2]))
        tail = received[-4800:]
        def energy(hz):
            return abs(sum(v * complex(math.cos(2 * math.pi * hz * i / RATE),
                                       math.sin(2 * math.pi * hz * i / RATE)) for i, v in enumerate(tail)))
        self.assertGreater(energy(1000), 20 * energy(440))
        with self.assertRaises(ValueError):
            encoder.audio_packets(b'wrong frame size')


if __name__ == '__main__':
    unittest.main()
