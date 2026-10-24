"""Configuration and realtime-callback backpressure checks (no SIP endpoint)."""
import asyncio
from pathlib import Path
import queue
import tempfile
import unittest

from transcription import ElevenStream, LocalSink
from sip_lab import WavAudio
from sip_transcription import Session


class TranscriptionTests(unittest.TestCase):
    def test_fixture_cannot_receive_real_credentials_or_target_remote_hosts(self):
        for url in ('ws://example.com:8000/test', 'wss://127.0.0.1:8000/test',
                    'ws://localhost:8000/test', 'ws://127.0.0.1:8000/test?key=x',
                    'ws://user:pass@127.0.0.1:8000/test'):
            with self.assertRaises(ValueError):
                ElevenStream(fixture_url=url)
        with self.assertRaises(ValueError):
            ElevenStream(key='secret', fixture_url='ws://127.0.0.1:8000/test')
        with self.assertRaises(ValueError):
            ElevenStream()

    def test_callback_queue_is_bounded_and_signals_overload(self):
        session = Session.__new__(Session)
        session.finished = session.overflow = False
        session.audio = queue.Queue(maxsize=100)
        for _ in range(1000):
            session.receive_pcm(bytes(640))
        self.assertTrue(session.overflow)
        self.assertEqual(session.audio.qsize(), 100)
        session.finished = True
        session.audio.get_nowait()
        session.receive_pcm(bytes(640))
        self.assertEqual(session.audio.qsize(), 99)


if __name__ == '__main__':
    unittest.main()
