import asyncio
import tempfile
import unittest

from sks_adapter import SimulatedSks, validate_event
from sks_lab import SksLab, run_scenarios


class AdapterTests(unittest.TestCase):
    def test_post_release_cap_and_idempotent_station_commands(self):
        now = [0.0]
        sks = SimulatedSks(clock=lambda: now[0])
        sks.ring('a')
        now[0] = 100
        sks.answer('a')
        sks.answer('a')
        self.assertTrue(sks.release('one'))
        self.assertEqual(sks.deadline, 110)
        now[0] = 102
        self.assertFalse(sks.release('second-click'))
        self.assertEqual(sks.deadline, 110)
        sks.relock()
        self.assertFalse(sks.release('second-click'))
        self.assertTrue(sks.release('three'))
        self.assertEqual(sks.deadline, 110)  # A fresh release cannot extend it either.
        sks.end()
        sks.end()
        commands = [e['command'] for e in sks.journal if e['event'] == 'command_acknowledged']
        self.assertEqual(commands, ['answer', 'door_release', 'door_release', 'hangup'])
        self.assertEqual(sks.status()['door_position'], 'unknown')
        sks.ring('b')
        now[0] += 115
        sks.answer('b')
        deadline = sks.deadline
        sks.release('four')
        self.assertEqual(sks.deadline, deadline)  # Original maximum is earlier.

    def test_unlock_without_answer_does_not_create_speech(self):
        sks = SimulatedSks()
        sks.ring('a')
        self.assertTrue(sks.release('one'))
        self.assertEqual(sks.state, 'ringing')
        commands = [e.get('command') for e in sks.journal]
        self.assertNotIn('answer', commands)

    def test_event_schema_rejects_ambiguous_inputs(self):
        for value in (None, [], {'event': 'door-call'}, {'event': 'visitor-left', 'call_id': '../x'},
                      {'event': 'floor-call', 'call_id': 'a'}, {'event': 'line-lost', 'extra': 1}):
            with self.assertRaises(ValueError):
                validate_event(value)
        self.assertEqual(validate_event({'event': 'door-call', 'call_id': 'visit-1'}), ('door-call', 'visit-1'))
        for value in (float('nan'), float('inf'), 0, -1):
            with self.assertRaises(ValueError):
                SimulatedSks(window=value)

    def test_replay_memory_and_journal_are_bounded(self):
        now = [0.0]
        sks = SimulatedSks(clock=lambda: now[0])
        for i in range(128):
            self.assertTrue(sks.ring(f'call-{i}'))
            sks.end()
        with self.assertRaises(ValueError):
            sks.ring('overflow')
        for _ in range(300):
            sks.note('test_event')
        self.assertEqual(len(sks.journal), 128)
        now[0] = 301
        self.assertTrue(sks.ring('fresh'))
        self.assertEqual(len(sks.calls), 1)


class AdapterScenarioTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_bell_events_report_one_accepted_call(self):
        with tempfile.TemporaryDirectory() as folder:
            lab = SksLab(folder)
            try:
                lab.calls.delay = .03
                results = await asyncio.gather(*(lab.bridge.input_event(
                    {'event': 'door-call', 'call_id': 'a'}) for _ in range(8)))
                self.assertEqual(sum(r['accepted'] for r in results), 1)
                self.assertEqual(lab.calls.rings, 1)
            finally:
                await lab.close()

    async def test_authenticated_http_adapter_scenarios(self):
        result = await run_scenarios()
        self.assertEqual(len(result['scenarios']), 8)
        self.assertTrue(all(s['result'] == 'passed' for s in result['scenarios']))

    async def test_line_loss_during_pending_ring_cannot_leave_late_call_running(self):
        with tempfile.TemporaryDirectory() as folder:
            lab = SksLab(folder)
            try:
                lab.calls.delay = .06
                ringing = asyncio.create_task(lab.bridge.input_event({'event': 'door-call', 'call_id': 'a'}))
                await asyncio.sleep(.01)
                loss = asyncio.create_task(lab.bridge.input_event({'event': 'line-lost'}))
                with self.assertRaises(ValueError):
                    await ringing
                await loss
                self.assertFalse(lab.audio.active)
                self.assertEqual(lab.calls.state, 'idle')
                self.assertFalse(lab.bridge.adapter.online)
                self.assertIsNone(lab.bridge.timer)
            finally:
                await lab.close()


if __name__ == '__main__':
    unittest.main()
