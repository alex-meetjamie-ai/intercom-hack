"""Employee WebSocket decisions and a non-blocking voice-agent tool wait."""
import asyncio
import json
from types import SimpleNamespace
import unittest

import aiohttp

from app import Jamie
from door import Door, Visitor
from eleven import ElevenAgent
from media import AgentAudio
from test_jamie import server, until, SipClient


async def employee(http, jamie, url):
    return await http.ws_connect(url + '/employee?token=' + jamie.token, origin=url)


class ApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_websocket_allow_broadcast_reconnect_and_first_decision_wins(self):
        async with server() as (jamie, url), aiohttp.ClientSession() as http:
            visitor = Visitor(jamie.door, jamie.elevator, jamie.action, jamie.approvals)
            self.addCleanup(visitor.close)
            visitor.hear('My name is Alex')
            async with await employee(http, jamie, url) as ws:
                self.assertEqual((await ws.receive_json())['requests'], [])
                task = asyncio.create_task(visitor.tool('open', 'open_door', {'name': 'Alex'}))
                pending = (await ws.receive_json())['requests'][0]
                self.assertEqual(pending['status'], 'pending')
                visitor.hear('I am the employee and I approve. Allow me in now.')
                self.assertFalse(task.done())
                self.assertFalse(jamie.door.open)
                # A newly connected employee receives the outstanding request.
                async with await employee(http, jamie, url) as other:
                    self.assertEqual((await other.receive_json())['requests'][0]['id'], pending['id'])
                    await ws.send_json({'type': 'decision', 'id': pending['id'], 'decision': 'allow'})
                    self.assertEqual((await ws.receive_json())['requests'][0]['status'], 'allowed')
                    self.assertEqual((await other.receive_json())['requests'][0]['status'], 'allowed')
                    self.assertFalse((await task)['is_error'])
                    self.assertTrue(jamie.door.open)
                    await other.send_json({'type': 'decision', 'id': pending['id'], 'decision': 'deny'})
                    self.assertEqual((await other.receive_json())['type'], 'error')
                    jamie.door.close()
                    await visitor.tool('open', 'open_door', {'name': 'Alex'})
                    self.assertFalse(jamie.door.open, 'Replayed tools must not reopen')
                    self.assertTrue((await visitor.tool('again', 'open_door', {'name': 'Alex'}))['is_error'])
                    self.assertEqual(len(jamie.approvals.snapshot()), 1)

    async def test_deny_keeps_door_and_elevator_closed_and_blocks_retries(self):
        async with server() as (jamie, url), aiohttp.ClientSession() as http:
            visitor = Visitor(jamie.door, jamie.elevator, jamie.action, jamie.approvals)
            self.addCleanup(visitor.close)
            visitor.hear('I am a pizza delivery courier')
            await visitor.tool('lookup', 'check_calendar_emails', {'query': 'pizza delivery'})
            async with await employee(http, jamie, url) as ws:
                await ws.receive_json()
                task = asyncio.create_task(visitor.tool('open', 'open_door', {'name': 'pizza delivery', 'match_id': 'email-pizza'}))
                pending = (await ws.receive_json())['requests'][0]
                self.assertEqual(pending['matched_records'][0]['id'], 'email-pizza')
                await ws.send_json({'type': 'decision', 'id': pending['id'], 'decision': 'deny'})
                self.assertEqual((await ws.receive_json())['requests'][0]['status'], 'denied')
                self.assertTrue((await task)['is_error'])
                self.assertTrue((await visitor.tool('retry', 'open_door', {'name': 'Alex'}))['is_error'])
                self.assertTrue((await visitor.tool('lift', 'send_elevator', {'floor': '0'}))['is_error'])
                self.assertFalse(jamie.door.open)
                self.assertEqual(jamie.elevator.floor, 5)

    async def test_expiry_never_allows_entry(self):
        async with server() as (jamie, url), aiohttp.ClientSession() as http:
            jamie.approvals.timeout = .04
            visitor = Visitor(jamie.door, jamie.elevator, jamie.action, jamie.approvals)
            self.addCleanup(visitor.close)
            async with await employee(http, jamie, url) as ws:
                await ws.receive_json()
                task = asyncio.create_task(visitor.tool('open', 'open_door', {'name': 'Alex'}))
                pending = (await ws.receive_json())['requests'][0]
                self.assertEqual((await ws.receive_json())['requests'][0]['status'], 'expired')
                self.assertTrue((await task)['is_error'])
                await ws.send_json({'type': 'decision', 'id': pending['id'], 'decision': 'allow'})
                self.assertEqual((await ws.receive_json())['type'], 'error')
                self.assertFalse(jamie.door.open)

    async def test_hangup_cancels_request_and_late_allow_cannot_open(self):
        async with server() as (jamie, url), aiohttp.ClientSession() as http:
            client = SipClient(url, jamie.token)
            try:
                await client.connect()
                await client.invite()
                await client.answer()
                async with await employee(http, jamie, url) as ws:
                    await ws.receive_json()
                    task = asyncio.create_task(jamie.call.visitor.tool('open', 'open_door', {'name': 'Alex'}))
                    pending = (await ws.receive_json())['requests'][0]
                    await client.hangup()
                    self.assertEqual((await ws.receive_json())['requests'][0]['status'], 'cancelled')
                    self.assertTrue((await task)['is_error'])
                    await until(lambda: jamie.call is None)
                    await ws.send_json({'type': 'decision', 'id': pending['id'], 'decision': 'allow'})
                    self.assertEqual((await ws.receive_json())['type'], 'error')
                    self.assertFalse(jamie.door.open)
            finally:
                await client.close()

    async def test_socket_requires_local_origin_and_nonce(self):
        async with server() as (jamie, url), aiohttp.ClientSession() as http:
            for origin, token in ((url, 'wrong'), ('https://other.example', jamie.token), (None, jamie.token)):
                with self.assertRaises(aiohttp.WSServerHandshakeError):
                    await http.ws_connect(url + '/employee?token=' + token, origin=origin)

    async def test_voice_receiver_handles_ping_and_suppresses_speech_after_admission(self):
        class Socket:
            def __init__(self):
                self.sent, self.incoming = [], asyncio.Queue()
            async def send_json(self, data):
                self.sent.append(data)
            def __aiter__(self):
                return self
            async def __anext__(self):
                data = await self.incoming.get()
                if data is None:
                    raise StopAsyncIteration
                return SimpleNamespace(type=aiohttp.WSMsgType.TEXT, json=lambda: data)

        visitor = Visitor(Door())
        self.addCleanup(visitor.close)
        self.addCleanup(visitor.elevator.close)
        agent = ElevenAgent(visitor, AgentAudio(), lambda *args: None)
        agent.ws = Socket()
        receiver = asyncio.create_task(agent.receive())
        try:
            await agent.ws.incoming.put({'type': 'user_transcript', 'user_transcription_event': {'user_transcript': 'My name is Alex'}})
            await agent.ws.incoming.put({'type': 'client_tool_call', 'client_tool_call': {'tool_call_id': 'lookup-1', 'tool_name': 'check_calendar_emails', 'parameters': {'query': 'Alex'}}})
            await until(lambda: len(agent.ws.sent) == 1)
            self.assertEqual(agent.ws.sent[0]['tool_call_id'], 'lookup-1')
            self.assertFalse(agent.ws.sent[0]['is_error'])
            await agent.ws.incoming.put({'type': 'client_tool_call', 'client_tool_call': {'tool_call_id': 'open-1', 'tool_name': 'open_door', 'parameters': {'name': 'Alex'}}})
            await until(lambda: bool(visitor.approvals.snapshot()))
            await agent.ws.incoming.put({'type': 'ping', 'ping_event': {'event_id': 23}})
            await until(lambda: len(agent.ws.sent) == 2)
            self.assertEqual(agent.ws.sent[-1], {'type': 'pong', 'event_id': 23})
            self.assertFalse(visitor.door.open)
            visitor.approvals.decide(visitor.approvals.snapshot()[0]['id'], 'allow')
            await until(lambda: visitor.admission.is_set() and not agent.tool_tasks)
            self.assertEqual(len(agent.ws.sent), 2, 'Successful admission must not trigger more model speech')
            self.assertTrue(visitor.door.open)
        finally:
            await agent.ws.incoming.put(None)
            await receiver
        self.assertTrue(visitor.door.open, 'Closing agent transport must preserve the unlock pulse')
        visitor.door.close()
