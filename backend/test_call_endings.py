"""Refused calls finish over real SIP after audio playout, without unlocking."""
import asyncio
import base64
from types import SimpleNamespace
import unittest

import aiohttp

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
    async def start(self):
        self.ws = Socket()
        self.task = asyncio.create_task(self.receive())
        self.output.push(tone(.1))
        self.ready.set()


class CallEndingTests(unittest.IsolatedAsyncioTestCase):
    async def check_refusal(self, decision):
        async with server(LocalEleven) as (jamie, url):
            if decision == 'expired':
                jamie.approvals.timeout = .08
            client = SipClient(url, jamie.token)
            try:
                await client.connect()
                await client.invite()
                await client.answer()
                await until(lambda: client.nonzero > 500)
                call = jamie.call
                agent = call.agent
                await agent.ws.incoming.put({'type': 'client_tool_call', 'client_tool_call': {
                    'tool_call_id': 'open', 'tool_name': 'open_door', 'parameters': {'name': 'parcel delivery'}}})
                await until(lambda: bool(jamie.approvals.snapshot()))
                if decision == 'denied':
                    jamie.approvals.decide(jamie.approvals.snapshot()[0]['id'], 'deny')
                await until(lambda: agent.refusing)
                self.assertEqual(call.visitor.entry_decision['status'], decision)
                self.assertEqual(agent.ws.sent[-1]['type'], 'client_tool_result')
                audible_before = client.nonzero
                await agent.ws.incoming.put({'type': 'agent_response', 'agent_response_event': {
                    'agent_response': "Sorry, I can't let you in."}})
                await asyncio.sleep(.1)
                self.assertFalse(agent.finished.is_set(), 'Transcript alone must not end the call')
                await agent.ws.incoming.put({'type': 'audio', 'audio_event': {
                    'audio_base_64': base64.b64encode(tone(1.6)).decode()}})
                await until(lambda: bool(agent.output.buffer))
                await agent.ws.incoming.put({'type': 'interruption'})
                await asyncio.sleep(.2)
                self.assertIs(jamie.call, call)
                self.assertTrue(agent.output.buffer, 'A late interruption must not cut off the refusal')
                await client.accept_hangup(timeout=4)
                await until(lambda: jamie.call is None)
                self.assertGreater(client.nonzero - audible_before, 20000, 'Caller must hear the refusal before BYE')
                self.assertFalse(jamie.door.open)
                self.assertEqual(jamie.elevator.floor, 5)
                self.assertIsNone(jamie.error)
                self.assertEqual(jamie.phase, 'idle')
            finally:
                await client.close()

    async def test_deny_plays_refusal_then_hangs_up(self):
        await self.check_refusal('denied')

    async def test_expired_approval_plays_refusal_then_hangs_up(self):
        await self.check_refusal('expired')

    async def test_missing_refusal_audio_cannot_leave_call_open(self):
        class StalledEleven(LocalEleven):
            refusal_timeout = .25

        async with server(StalledEleven) as (jamie, url):
            jamie.approvals.timeout = .04
            client = SipClient(url, jamie.token)
            try:
                await client.connect()
                await client.invite()
                await client.answer()
                agent = jamie.call.agent
                await agent.ws.incoming.put({'type': 'client_tool_call', 'client_tool_call': {
                    'tool_call_id': 'open', 'tool_name': 'open_door', 'parameters': {'name': 'Alex'}}})
                await client.accept_hangup()
                await until(lambda: jamie.call is None)
                self.assertFalse(jamie.door.open)
                self.assertIsNone(jamie.error)
                self.assertTrue(agent.finish_task.done())
            finally:
                await client.close()
