"""Private ElevenLabs agent websocket. The browser never sees its credentials."""
import asyncio
import base64
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent


class AgentError(RuntimeError):
    pass


class ElevenAgent:
    def __init__(self, visitor, output, transcript):
        self.visitor, self.output, self.transcript = visitor, output, transcript
        self.http = self.ws = self.task = None
        self.input_samples = 0
        self.ready = asyncio.Event()
        self.closed = asyncio.Event()
        self.error = None

    async def start(self):
        load_dotenv(ROOT / '.env')
        key = os.getenv('ELEVENLABS_API_KEY')
        path = ROOT / '.state/agent.json'
        if not key or not path.exists():
            raise AgentError('ElevenLabs agent is not configured. Run backend/setup_agent.py.')
        agent_id = json.loads(path.read_text())['agent_id']
        self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15), trust_env=False)
        try:
            async with self.http.get('https://api.elevenlabs.io/v1/convai/conversation/get-signed-url',
                    params={'agent_id': agent_id}, headers={'xi-api-key': key}, allow_redirects=False) as response:
                if response.status != 200:
                    raise AgentError(f'ElevenLabs authorization failed (HTTP {response.status}). Check Agents permissions.')
                signed = (await response.json())['signed_url']
            target = urlsplit(signed)
            if target.scheme != 'wss' or target.hostname != 'api.elevenlabs.io':
                raise AgentError('Unexpected ElevenLabs WebSocket destination')
            self.ws = await self.http.ws_connect(signed, max_msg_size=2**20, heartbeat=20)
            await self.ws.send_json({'type': 'conversation_initiation_client_data'})
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
                    self.output.push(base64.b64decode(data['audio_event']['audio_base_64'], validate=True))
                elif kind == 'interruption':
                    self.output.interrupt()
                elif kind == 'ping':
                    await self.ws.send_json({'type': 'pong', 'event_id': data['ping_event']['event_id']})
                elif kind == 'user_transcript':
                    text = data['user_transcription_event']['user_transcript'][:2000]
                    self.visitor.hear(text)
                    self.transcript('You', text)
                elif kind == 'agent_response':
                    self.transcript('Jamie', data['agent_response_event']['agent_response'][:2000])
                elif kind == 'client_tool_call':
                    tool = data['client_tool_call']
                    result = self.visitor.tool(tool['tool_call_id'], tool['tool_name'], tool.get('parameters'))
                    await self.ws.send_json({'type': 'client_tool_result',
                                            'tool_call_id': tool['tool_call_id'], **result})
                elif kind == 'error' or 'error' in data:
                    raise AgentError('ElevenLabs reported a conversation error')
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = str(exc) if isinstance(exc, AgentError) else 'ElevenLabs connection failed'
        finally:
            self.ready.set()
            self.closed.set()

    async def send(self, pcm):
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
