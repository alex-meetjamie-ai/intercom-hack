"""Real SIP tests for timed updates, instructions before unlock and refusal."""
import asyncio
from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import aiohttp

from announcements import TEXT, wait_schedule, entry_message
from eleven import ElevenAgent
from test_jamie import SipClient, server, tone, until


class Socket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = []
        self.closed = False

    async def send_json(self, data):
        if 'user_audio_chunk' not in data:
            self.sent.append(data)

    async def close(self):
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        data = await self.incoming.get()
        if data is None:
            raise StopAsyncIteration
        return SimpleNamespace(type=aiohttp.WSMsgType.TEXT, json=lambda: data)


class LocalEleven(ElevenAgent):
    wait_schedule = staticmethod(lambda timeout: wait_schedule(timeout, interval=.35, jitter=.02))

    async def start(self):
        self.ws = Socket()
        self.clips = {name: tone(.04) for name in TEXT}
        self.clips.update(entry=tone(1.2), timeout=tone(.8), denied=tone(.8))
        self.task = asyncio.create_task(self.receive())
        self.output.push(tone(.1))
        self.ready.set()


async def request_entry(agent, personal_name=None):
    parameters = {'name': 'Alex'}
    if personal_name:
        parameters['personal_name'] = personal_name
    await agent.ws.incoming.put({'type': 'client_tool_call', 'client_tool_call': {
        'tool_call_id': 'open', 'tool_name': 'open_door', 'parameters': parameters}})


class CallEndingTests(unittest.IsolatedAsyncioTestCase):
    async def check_refusal(self, decision):
        async with server(LocalEleven) as (jamie, url):
            if decision == 'expired':
                jamie.approvals.timeout = 1.1
            client = SipClient(url, jamie.token)
            try:
                await client.connect()
                await client.invite()
                await client.answer()
                await until(lambda: client.nonzero > 500)
                call = jamie.call
                agent = call.agent
                await request_entry(agent)
                await until(lambda: bool(jamie.approvals.snapshot()))
                if decision == 'denied':
                    jamie.approvals.decide(jamie.approvals.snapshot()[0]['id'], 'deny')
                await until(lambda: agent.refusing)
                self.assertEqual(call.visitor.entry_decision['status'], decision)
                self.assertFalse(agent.ws.sent, 'Final decisions must not trigger duplicate model speech')
                audible_before = client.nonzero
                await agent.ws.incoming.put({'type': 'interruption'})
                await agent.ws.incoming.put({'type': 'agent_response', 'agent_response_event': {
                    'agent_response': 'Unwanted duplicate refusal'}})
                await asyncio.sleep(.15)
                self.assertIs(jamie.call, call)
                self.assertTrue(agent.output.buffer, 'Late model events must not cut off the announcement')
                await client.accept_hangup(timeout=3)
                await until(lambda: jamie.call is None)
                self.assertGreater(client.nonzero - audible_before, 9000)
                self.assertFalse(jamie.door.open)
                self.assertEqual(jamie.elevator.floor, 5)
                self.assertIsNone(jamie.error)
                spoken = [m['text'] for m in jamie.messages]
                self.assertNotIn('Unwanted duplicate refusal', spoken)
                self.assertEqual(spoken.count(TEXT['timeout' if decision == 'expired' else 'denied']), 1)
                if decision == 'expired':
                    self.assertEqual(spoken, [TEXT[k] for k in ('reaching', 'trying', 'waiting', 'timeout')])
                    request = jamie.approvals.snapshot()[0]
                    elapsed = (datetime.fromisoformat(request['decided_at']) - datetime.fromisoformat(request['created_at'])).total_seconds()
                    self.assertAlmostEqual(elapsed, 1.1, delta=.15)
            finally:
                await client.close()

    async def test_deny_plays_refusal_then_hangs_up(self):
        await self.check_refusal('denied')

    async def test_expiry_speaks_updates_then_apology_and_hangup(self):
        await self.check_refusal('expired')

    async def check_allowed(self, hangup=False, missing_audio=False, personal_name=None, expected_name=None):
        async with server(LocalEleven) as (jamie, url):
            client = SipClient(url, jamie.token)
            try:
                await client.connect()
                await client.invite()
                await client.answer()
                await until(lambda: client.nonzero > 500)
                agent = jamie.call.agent
                if missing_audio:
                    del agent.clips['entry']
                await request_entry(agent, personal_name)
                await until(lambda: bool(jamie.approvals.snapshot()))
                jamie.approvals.decide(jamie.approvals.snapshot()[0]['id'], 'allow')
                if not missing_audio:
                    await until(lambda: any(m['text'] == entry_message(expected_name) for m in jamie.messages))
                    self.assertFalse(jamie.door.open)
                    await asyncio.sleep(.3)
                    self.assertFalse(jamie.door.open, 'Instructions must finish before the door opens')
                if hangup:
                    await client.hangup()
                else:
                    await client.accept_hangup(timeout=4)
                await until(lambda: jamie.call is None)
                self.assertEqual(jamie.door.open, not (hangup or missing_audio))
                self.assertEqual(jamie.elevator.floor, 5 if hangup or missing_audio else 0)
                if missing_audio:
                    self.assertIsNotNone(jamie.error)
                else:
                    self.assertIsNone(jamie.error)
            finally:
                await client.close()

    async def test_allowed_instructions_finish_before_unlock_and_bye(self):
        await self.check_allowed()

    async def test_personal_name_is_spoken_before_unlock(self):
        with patch('eleven.load_announcements', new_callable=AsyncMock,
                   return_value={'entry': tone(1.2)}) as render:
            await self.check_allowed(personal_name='Alex', expected_name='Alex')
        self.assertEqual(render.call_args.kwargs['texts'], {'entry': entry_message('Alex')})
        self.assertFalse(render.call_args.kwargs['cache_audio'])

    async def test_name_generation_failure_plays_complete_generic_directions(self):
        with patch('eleven.load_announcements', new_callable=AsyncMock, side_effect=TimeoutError):
            await self.check_allowed(personal_name='Alex')

    async def test_hangup_during_instructions_never_opens(self):
        await self.check_allowed(hangup=True)

    async def test_missing_instruction_audio_fails_closed(self):
        await self.check_allowed(missing_audio=True)
