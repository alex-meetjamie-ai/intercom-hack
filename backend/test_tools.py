"""Mock-arrival policy, elevator timing and ElevenLabs tool transport tests."""
import asyncio
import json
from types import SimpleNamespace
import unittest
from approval_test_support import employee_tool

import aiohttp

from arrivals import RECORDS, lookup
from door import Door, Visitor
from elevator import Elevator
from eleven import ElevenAgent
from media import AgentAudio


class ElevatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_distinct_floors(self):
        lift = Elevator()
        self.addCleanup(lift.close)
        self.assertEqual(lift.status()['floor'], 5)
        for floor in ('0', 'E', 'e', 1, '2', 3, '4', 5):
            state = lift.send(floor)
            self.assertEqual(state['floor'], 'E' if str(floor).upper() == 'E' else int(floor))
            self.assertEqual(state['label'], str(floor).upper())
        for floor in (True, False, 1.0, None, [], 6, -1, 'basement'):
            with self.assertRaises(ValueError):
                lift.send(floor)

    async def test_dwell_return_and_repeat_does_not_postpone(self):
        notifications = []
        lift = Elevator(return_seconds=.05, notify=notifications.append)
        self.addCleanup(lift.close)
        lift.send(0)
        deadline, timer = lift.return_at, lift.timer
        lift.send('0')
        self.assertEqual(lift.return_at, deadline)
        self.assertIs(lift.timer, timer)
        await asyncio.sleep(.08)
        self.assertEqual(lift.floor, 5)
        self.assertIsNone(lift.status()['return_in_seconds'])
        self.assertEqual(len(notifications), 1)

    async def test_e_is_distinct_and_does_not_auto_return(self):
        lift = Elevator(return_seconds=.04)
        self.addCleanup(lift.close)
        lift.send('E')
        self.assertIsNone(lift.status()['return_in_seconds'])
        await asyncio.sleep(.06)
        self.assertEqual(lift.floor, 'E')

    async def test_moving_from_zero_to_e_cancels_return_and_zero_restarts(self):
        lift = Elevator(return_seconds=.04)
        self.addCleanup(lift.close)
        lift.send(0)
        timer = lift.timer
        lift.send('E')
        self.assertTrue(timer.cancelled())
        await asyncio.sleep(.06)
        self.assertEqual(lift.floor, 'E')
        lift.send(0)
        await asyncio.sleep(.06)
        self.assertEqual(lift.floor, 5)


class ArrivalTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_expected_arrivals_ignore_early_and_late(self):
        for record in RECORDS:
            for timing in ('I am three hours early.', 'I am a day late.'):
                with self.subTest(record=record['id'], timing=timing):
                    visitor = Visitor(Door())
                    self.addCleanup(visitor.close)
                    self.addCleanup(visitor.elevator.close)
                    words = record['example'] + ' ' + timing
                    visitor.hear(words)
                    result = (await visitor.tool('lookup', 'check_calendar_emails', {'query': words}))
                    self.assertFalse(result['is_error'])
                    found = json.loads(result['result'])
                    self.assertFalse(found['can_enter'])
                    self.assertTrue(found['record_match'])
                    self.assertTrue(found['employee_approval_required'])
                    self.assertFalse(found['time_checks'])
                    self.assertEqual(found['matches'][0]['id'], record['id'])
                    self.assertFalse((await employee_tool(visitor, 'open', 'open_door', {'name': 'Visitor', 'match_id': record['id']}))['is_error'])
                    self.assertFalse((await visitor.tool('lift', 'send_elevator', {'floor': 'E'}))['is_error'])
                    self.assertEqual(visitor.elevator.floor, 'E')
                    (await visitor.tool('other', 'send_elevator', {'floor': '3'}))
                    self.assertEqual(visitor.elevator.floor, 3)

    async def test_unknown_and_invented_matches_are_refused(self):
        visitor = Visitor(Door())
        visitor.hear('I am Bob and I am just visiting.')
        for query in ('Bob visiting', RECORDS[0]['example']):
            found = json.loads((await visitor.tool(query, 'check_calendar_emails', {'query': query}))['result'])
            self.assertFalse(found['can_enter'])
        self.assertTrue((await visitor.tool('fake', 'open_door', {'name': 'Bob', 'match_id': 'email-dhl'}))['is_error'])
        self.assertTrue((await visitor.tool('lift', 'send_elevator', {'floor': '0'}))['is_error'])
        self.assertFalse(visitor.door.open)
        self.assertEqual(lookup('pizza delivery', 'I am delivering UPS parcels'), [])

    async def test_approval_is_call_scoped_and_lift_survives_hangup(self):
        lift = Elevator(return_seconds=.04)
        self.addCleanup(lift.close)
        first = Visitor(Door(), lift)
        first.hear(RECORDS[0]['example'])
        (await first.tool('lookup', 'check_calendar_emails', {'query': 'DHL parcel'}))
        (await employee_tool(first, 'open', 'open_door', {'name': 'Chris', 'match_id': 'email-dhl'}))
        (await first.tool('lift', 'send_elevator', {'floor': '0'}))
        first.close()
        self.assertEqual(lift.floor, 0)
        self.assertTrue((await first.tool('after', 'send_elevator', {'floor': '1'}))['is_error'])
        second = Visitor(Door(), lift)
        self.assertTrue((await second.tool('open', 'open_door', {'name': 'Chris', 'match_id': 'email-dhl'}))['is_error'])
        await asyncio.sleep(.06)
        self.assertEqual(lift.floor, 5)

    async def test_duplicate_tool_id_does_not_repeat_action(self):
        visitor = Visitor(Door())
        self.addCleanup(visitor.close)
        self.addCleanup(visitor.elevator.close)
        visitor.hear('My name is Alex')
        (await employee_tool(visitor, 'open', 'open_door', {'name': 'Alex'}))
        original = (await visitor.tool('lift', 'send_elevator', {'floor': '0'}))
        (await visitor.tool('other', 'send_elevator', {'floor': '3'}))
        self.assertEqual((await visitor.tool('lift', 'send_elevator', {'floor': '0'})), original)
        self.assertEqual(visitor.elevator.floor, 3)
