"""Admin sources and decision evidence, with no external services."""
import unittest
from approval_test_support import employee_tool

import aiohttp

from arrivals import RECORDS
from door import Visitor
from test_jamie import SipClient, server, until


class AdminTests(unittest.IsolatedAsyncioTestCase):
    async def test_records_are_lookup_source_and_api_is_local_only(self):
        async with server() as (jamie, url), aiohttp.ClientSession() as http:
            async with http.get(url + '/api/admin') as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                data = await response.json()
            self.assertEqual(data['records'], RECORDS)
            self.assertEqual(len([r for r in data['records'] if r['source'] == 'email']), 2)
            self.assertEqual(len([r for r in data['records'] if r['source'] == 'calendar']), 2)
            self.assertFalse(data['time_checks'])
            self.assertTrue(data['mock'])
            self.assertNotIn('token', data)
            self.assertNotIn('agent_configured', data)
            self.assertEqual(data['actions'], [])
            for headers in ({'Origin': 'https://other.example'}, {'Host': 'other.example'}):
                async with http.get(url + '/api/admin', headers=headers) as response:
                    self.assertEqual(response.status, 403)

    async def test_sip_call_records_evidence_and_next_call_clears_review(self):
        async with server() as (jamie, url), aiohttp.ClientSession() as http:
            first = SipClient(url, jamie.token)
            try:
                await first.connect()
                await first.invite()
                await first.answer()
                visitor = jamie.call.visitor
                words = "I'm Chris from DHL, delivering a parcel. I am very late."
                visitor.hear(words)
                jamie.transcript('You', words)
                arguments = {'query': 'DHL parcel delivery'}
                lookup = (await visitor.tool('lookup', 'check_calendar_emails', arguments))
                arguments['query'] = 'changed after the call'
                (await employee_tool(visitor, 'unlock', 'open_door', {'name': 'Chris', 'match_id': 'email-dhl'}))
                self.assertEqual((await visitor.tool('lookup', 'check_calendar_emails', {})), lookup)
                await first.accept_hangup()
                await until(lambda: jamie.call is None)
                async with http.get(url + '/api/admin') as response:
                    data = await response.json()
                self.assertEqual(data['call'], 'idle')
                self.assertEqual(len(data['actions']), 5, 'Replayed tool call must not duplicate evidence')
                evidence = data['actions'][0]['evidence']
                self.assertEqual(evidence['arguments']['query'], 'DHL parcel delivery')
                self.assertIn(words.casefold(), evidence['heard'])
                self.assertEqual(evidence['matched_records'][0]['id'], 'email-dhl')
                self.assertFalse(evidence['output']['can_enter'])
                self.assertTrue(evidence['output']['record_match'])
                self.assertFalse(evidence['output']['time_checks'])
                self.assertEqual(data['actions'][3]['evidence']['basis'], 'employee_approval')
                self.assertEqual(data['actions'][4]['evidence']['output']['floor'], 0)
                self.assertEqual(data['transcript'][-1]['text'], words)
            finally:
                await first.close()
            second = SipClient(url, jamie.token)
            try:
                await second.connect()
                await second.invite()
                await second.answer()
                self.assertEqual(jamie.admin()['actions'], [])
                self.assertFalse(any(m['speaker'] == 'You' for m in jamie.admin()['transcript']))
                await second.hangup()
            finally:
                await second.close()

    async def test_no_match_invalid_record_and_employee_approval_are_distinct(self):
        async with server() as (jamie, url):
            visitor = Visitor(jamie.door, jamie.elevator, jamie.action)
            self.addCleanup(visitor.close)
            visitor.hear('My name is Bob and I am just visiting.')
            (await visitor.tool('lookup', 'check_calendar_emails', {'query': 'Bob visiting'}))
            (await visitor.tool('unlock', 'open_door', {'name': 'Bob', 'match_id': 'email-dhl'}))
            no_match, blocked = jamie.admin()['actions']
            self.assertTrue(no_match['ok'], 'A successful search with no match is not a tool error')
            self.assertFalse(no_match['evidence']['output']['can_enter'])
            self.assertEqual(no_match['evidence']['matched_records'], [])
            self.assertFalse(blocked['ok'])
            self.assertNotIn('basis', blocked['evidence'])
            self.assertFalse(jamie.door.open)
            visitor.hear('My name is Alex')
            (await employee_tool(visitor, 'alex', 'open_door', {'name': 'Alex'}))
            admitted = jamie.admin()['actions'][-1]
            self.assertTrue(admitted['ok'])
            self.assertEqual(admitted['evidence']['basis'], 'employee_approval')
            self.assertEqual(admitted['evidence']['matched_records'], [])
