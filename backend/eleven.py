"""Private ElevenLabs agent websocket. The browser never sees its credentials."""
import asyncio
import base64
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
from dotenv import load_dotenv
from announcements import load_announcements, TEXT, wait_schedule, entry_message

ROOT = Path(__file__).resolve().parent


class AgentError(RuntimeError):
    pass


class ElevenAgent:
    wait_schedule = staticmethod(wait_schedule)
    def __init__(self, visitor, output, transcript):
        self.visitor, self.output, self.transcript = visitor, output, transcript
        self.http = self.ws = self.task = None
        self.input_samples = 0
        self.ready = asyncio.Event()
        self.closed = asyncio.Event()
        self.finished = asyncio.Event()
        self.error = None
        self.tool_tasks = set()
        self.refusing = False
        self.managing_entry = False
        self.clips = {}
        self.announcement_texts = dict(TEXT)
        self.api_key = self.agent_id = None
        self.visitor.approval_waiter = self.wait_for_approval
        self.visitor.before_open = self.entry_instructions

    async def announce(self, name):
        if not self.visitor.active or self.closed.is_set():
            raise asyncio.CancelledError
        pcm = self.clips[name]
        self.transcript('Jamie', self.announcement_texts[name])
        self.output.push(pcm)
        async with asyncio.timeout(len(self.output.buffer) / 32000 + 3):
            await self.output.drain()

    async def wait_for_approval(self, context):
        # The model is paused on a tool. Local announcements keep the caller
        # informed without additional model turns, duplicated speech or delays.
        self.managing_entry = True
        self.output.interrupt()
        started = asyncio.get_running_loop().time()
        decision = asyncio.create_task(self.visitor.approvals.ask(self.visitor, context))
        try:
            for offset, message in self.wait_schedule(self.visitor.approvals.timeout):
                delay = max(0, started + offset - asyncio.get_running_loop().time())
                done, _ = await asyncio.wait({decision}, timeout=delay)
                if done:
                    break
                # Do not start an update that would overlap the timeout apology.
                remaining = self.visitor.approvals.timeout - (asyncio.get_running_loop().time() - started)
                if len(self.clips[message]) / 32000 + .2 < remaining:
                    await self.announce(message)
            return await decision
        finally:
            if not decision.done():
                decision.cancel()
            await asyncio.gather(decision, return_exceptions=True)

    async def entry_instructions(self):
        # Visitor checks that the call is still active after this finishes.
        # The door must remain closed until the full instruction was played.
        name = (self.visitor.entry_decision or {}).get('personal_name')
        if name:
            text = entry_message(name)
            try:
                async with asyncio.timeout(5):
                    clips = await load_announcements(self.http, self.api_key, self.agent_id,
                                                     texts={'entry': text}, cache_audio=False)
                self.clips['entry'] = clips['entry']
                self.announcement_texts['entry'] = text
            except (TimeoutError, aiohttp.ClientError, RuntimeError):
                # The optional name must not prevent the full cached directions.
                pass
        await self.announce('entry')

    async def run_tool(self, tool):
        try:
            result = await self.visitor.tool(tool['tool_call_id'], tool['tool_name'], tool.get('parameters'))
            if tool['tool_name'] == 'open_door' and not result['is_error']:
                # Admission triggers SIP hangup. Do not prompt another spoken
                # model response while the backend finishes the call.
                return
            decision = self.visitor.entry_decision or {}
            if tool['tool_name'] in ('open_door', 'deny_entry') and decision.get('status') in ('denied', 'expired'):
                self.refusing = True
                self.managing_entry = True
                if tool['tool_name'] == 'deny_entry':
                    self.output.interrupt()
                await self.announce('timeout' if decision['status'] == 'expired' else 'denied')
                self.finished.set()
                return  # Do not ask the model to generate a second farewell.
            if not self.closed.is_set():
                await self.ws.send_json({'type': 'client_tool_result', 'tool_call_id': tool['tool_call_id'], **result})
        except asyncio.CancelledError:
            raise
        except Exception:
            self.error = 'Could not complete the tool request.'
            self.closed.set()

    async def start(self):
        load_dotenv(ROOT / '.env')
        key = os.getenv('ELEVENLABS_API_KEY')
        path = ROOT / '.state/agent.json'
        if not key or not path.exists():
            raise AgentError('ElevenLabs agent is not configured. Run backend/setup_agent.py.')
        agent_id = json.loads(path.read_text())['agent_id']
        self.api_key, self.agent_id = key, agent_id
        self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15), trust_env=False)
        try:
            self.clips = await load_announcements(self.http, key, agent_id)
            async with self.http.get('https://api.elevenlabs.io/v1/convai/conversation/get-signed-url',
                    params={'agent_id': agent_id}, headers={'xi-api-key': key}, allow_redirects=False) as response:
                if response.status != 200:
                    raise AgentError(f'ElevenLabs authorization failed (HTTP {response.status}). Check Agents permissions.')
                signed = (await response.json())['signed_url']
            target = urlsplit(signed)
            if target.scheme != 'wss' or target.hostname != 'api.elevenlabs.io':
                raise AgentError('Unexpected ElevenLabs WebSocket destination')
            self.ws = await self.http.ws_connect(signed, max_msg_size=2**20, heartbeat=20)
            await self.ws.send_json({
                'type': 'conversation_initiation_client_data',
                'dynamic_variables': {'recent_calls': json.dumps(self.visitor.recent_calls, ensure_ascii=False)},
            })
            self.task = asyncio.create_task(self.receive())
            await asyncio.wait_for(self.ready.wait(), 15)
            if self.error:
                raise AgentError(self.error)
            if self.closed.is_set():
                raise AgentError('ElevenLabs closed the conversation before audio was ready')
        except BaseException:
            await self.close()
            raise

    async def receive(self):
        try:
            async for message in self.ws:
                if message.type != aiohttp.WSMsgType.TEXT:
                    continue
                data = message.json()
                kind = data.get('type')
                if kind == 'conversation_initiation_metadata':
                    meta = data['conversation_initiation_metadata_event']
                    if (meta['user_input_audio_format'] != 'pcm_16000' or
                            meta['agent_output_audio_format'] != 'pcm_16000'):
                        raise AgentError('Agent audio format must be pcm_16000 in both directions')
                    self.ready.set()
                elif kind == 'audio':
                    if not self.managing_entry:
                        self.output.push(base64.b64decode(data['audio_event']['audio_base_64'], validate=True))
                elif kind == 'interruption':
                    if not self.managing_entry:
                        self.output.interrupt()
                elif kind == 'ping':
                    await self.ws.send_json({'type': 'pong', 'event_id': data['ping_event']['event_id']})
                elif kind == 'user_transcript':
                    text = data['user_transcription_event']['user_transcript'][:2000]
                    self.visitor.hear(text)
                    self.transcript('You', text)
                elif kind == 'agent_response':
                    if not self.managing_entry:
                        self.transcript('Jamie', data['agent_response_event']['agent_response'][:2000])
                elif kind == 'client_tool_call':
                    tool = data['client_tool_call']
                    task = asyncio.create_task(self.run_tool(tool))
                    self.tool_tasks.add(task)
                    task.add_done_callback(self.tool_tasks.discard)
                elif kind == 'error' or 'error' in data:
                    raise AgentError('ElevenLabs reported a conversation error')
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = str(exc) if isinstance(exc, AgentError) else 'ElevenLabs connection failed'
        finally:
            self.visitor.close()
            tasks = list(self.tool_tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.ready.set()
            self.closed.set()

    async def send(self, pcm):
        if self.managing_entry:
            # Maintain a continuous input stream while the office owns the
            # decision. Visitor speech cannot interrupt the final announcements.
            pcm = bytes(len(pcm))
        if not self.ws or self.ws.closed or self.closed.is_set():
            raise AgentError(self.error or 'ElevenLabs conversation ended')
        await asyncio.wait_for(self.ws.send_json({'user_audio_chunk': base64.b64encode(pcm).decode()}), 5)
        self.input_samples += len(pcm) // 2

    async def close(self):
        self.closed.set()
        if self.task and self.task is not asyncio.current_task():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.ws:
            await self.ws.close()
        if self.http:
            await self.http.close()
