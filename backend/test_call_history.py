"""Recent-call context must survive hangup without carrying unlock permission."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from announcements import TEXT
from call_history import RecentCalls
from test_call_endings import LocalEleven, request_entry
from test_jamie import SipClient, server, until


class HistoryTests(unittest.TestCase):
    def test_expiry_bounds_and_snapshot_isolation(self):
        now = datetime(2026, 10, 24, tzinfo=timezone.utc)
        history = RecentCalls(clock=lambda: now)
        visitor = SimpleNamespace(entry_decision=None, admitted=False)
        for i in range(7):
            history.remember(visitor, [{'speaker': 'You', 'text': str(i)}])
        snapshot = history.snapshot()
        self.assertEqual(len(snapshot), 5)
        self.assertEqual(snapshot[0]['transcript'][0]['text'], '2')
        snapshot[0]['transcript'][0]['text'] = 'modified'
        self.assertEqual(history.snapshot()[0]['transcript'][0]['text'], '2')
        now += timedelta(minutes=30)
        self.assertEqual(history.snapshot(), [])

    def test_actual_opening_is_separate_from_employee_allow(self):
        history = RecentCalls()
        visitor = SimpleNamespace(entry_decision={'name': 'Alex', 'status': 'allowed'}, admitted=False)
        history.remember(visitor, [])
        self.assertEqual(history.snapshot()[0]['employee_decision'], 'allowed')
        self.assertFalse(history.snapshot()[0]['door_opened'])

    def test_empty_calls_and_transcript_limits(self):
        history = RecentCalls()
        visitor = SimpleNamespace(entry_decision=None, admitted=False)
        history.remember(visitor, [])
        self.assertEqual(history.snapshot(), [])
        history.remember(visitor, [{'speaker': 'You', 'text': 'x' * 2000}] * 30)
        transcript = history.snapshot()[0]['transcript']
        self.assertEqual(len(transcript), 12)
        self.assertEqual(len(transcript[0]['text']), 500)


class ReturningCallTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_call_receives_history_but_requires_new_approval(self):
        async with server(LocalEleven) as (jamie, url):
            first_id = None
            for index, decision in enumerate(('allow', 'deny')):
                client = SipClient(url, jamie.token)
                try:
                    await client.connect()
                    await client.invite()
                    await client.answer()
                    call = jamie.call
                    if index == 0:
                        self.assertEqual(call.visitor.recent_calls, [])
                    else:
                        memory = call.visitor.recent_calls
                        self.assertEqual(len(memory), 1)
                        self.assertTrue(memory[0]['door_opened'])
                        self.assertEqual(memory[0]['visitor_label'], 'Alex')
                        self.assertIn(TEXT['entry'], [m['text'] for m in memory[0]['transcript']])
                        self.assertIsNone(call.visitor.entry_decision)
                        self.assertFalse(call.visitor.admitted)
                        self.assertEqual(call.visitor.approved, {})
                    await request_entry(call.agent)
                    await until(lambda: any(r['status'] == 'pending' for r in jamie.approvals.snapshot()))
                    pending = next(r for r in jamie.approvals.snapshot() if r['status'] == 'pending')
                    self.assertFalse(jamie.door.open)
                    if index == 0:
                        first_id = pending['id']
                    else:
                        self.assertNotEqual(pending['id'], first_id)
                    jamie.approvals.decide(pending['id'], decision)
                    await client.accept_hangup(timeout=6)
                    await until(lambda: jamie.call is None)
                    # Closing a call again must not duplicate history.
                    await call.close()
                    self.assertEqual(len(jamie.recent_calls.snapshot()), index + 1)
                finally:
                    await client.close()
            self.assertFalse(jamie.door.open)
            self.assertEqual(jamie.recent_calls.snapshot()[-1]['employee_decision'], 'denied')
            self.assertFalse(jamie.recent_calls.snapshot()[-1]['door_opened'])
