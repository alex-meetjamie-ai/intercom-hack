"""Jamie local prototype. Run: .venv/bin/python app.py; open localhost:8740."""
import argparse
from collections import deque
import json
import os
from pathlib import Path
import secrets

from aiohttp import web, WSMsgType
from dotenv import load_dotenv

from door import Door
from eleven import ElevenAgent
from sip import Message, handle

ROOT = Path(__file__).resolve().parent
WEBSITE = ROOT.parent / 'website'


class Jamie:
    def __init__(self, port=8740, agent_factory=ElevenAgent):
        self.host = f'127.0.0.1:{port}'
        self.origins = {f'http://127.0.0.1:{port}', f'http://localhost:{port}'}
        self.hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        self.contact = f'sip:jamie@127.0.0.1:{port};transport=ws'
        self.agent_factory = agent_factory
        self.door = Door()
        self.call = None
        self.phase, self.error = 'idle', None
        self.messages = deque(maxlen=30)
        self.last_audio = {}
        self.token = secrets.token_urlsafe(32)

    def transcript(self, who, text):
        self.messages.append({'speaker': who, 'text': text})

    def status(self):
        return {'door': 'open' if self.door.open else 'closed', 'simulated': True,
                'call': self.phase, 'error': self.error, 'transcript': list(self.messages),
                'agent_configured': (ROOT / '.state/agent.json').exists(),
                'audio': {'sent_samples': self.call.agent.input_samples,
                          'received_samples': self.call.output.received_samples} if self.call else self.last_audio}


def create_app(jamie):
    @web.middleware
    async def local_only(request, handler):
        if request.host not in jamie.hosts:
            raise web.HTTPForbidden(text='Local prototype only')
        origin = request.headers.get('Origin')
        if origin and origin not in jamie.origins:
            raise web.HTTPForbidden(text='Origin rejected')
        response = await handler(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        return response

    app = web.Application(middlewares=[local_only], client_max_size=131072)

    async def index(request):
        return web.FileResponse(WEBSITE / 'index.html')

    async def script(request):
        return web.FileResponse(WEBSITE / 'dist/app.js')

    async def style(request):
        return web.FileResponse(WEBSITE / 'style.css')

    async def how_it_works(request):
        return web.FileResponse(WEBSITE / 'how-it-works.html')

    async def diagram_style(request):
        return web.FileResponse(WEBSITE / 'diagram.css')

    async def diagram_script(request):
        return web.FileResponse(WEBSITE / 'src/diagram.js')

    async def status(request):
        return web.json_response(jamie.status())

    async def config(request):
        # Browser same-origin policy prevents foreign sites reading this nonce.
        return web.json_response({'token': jamie.token})

    async def sip_socket(request):
        if request.headers.get('Origin') not in jamie.origins:
            raise web.HTTPForbidden()
        token = request.query.get('token', '')
        if not secrets.compare_digest(token.encode(), jamie.token.encode()):
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse(protocols=['sip'], max_msg_size=131072, heartbeat=25)
        await ws.prepare(request)
        try:
            async for item in ws:
                if item.type != WSMsgType.TEXT:
                    continue
                if not item.data.strip():
                    if item.data == '\r\n\r\n':
                        await ws.send_str('\r\n')
                    continue
                try:
                    await handle(jamie, ws, Message.parse(item.data))
                except (ValueError, KeyError, IndexError):
                    await ws.close(code=1008, message=b'Malformed SIP')
                    break
        finally:
            if jamie.call and jamie.call.ws is ws:
                await jamie.call.close()
        return ws

    async def cleanup(app):
        if jamie.call:
            await jamie.call.close(send_bye=True)
        jamie.door.close()

    app.router.add_get('/', index)
    app.router.add_get('/app.js', script)
    app.router.add_get('/style.css', style)
    app.router.add_get('/how-it-works', how_it_works)
    app.router.add_get('/diagram.css', diagram_style)
    app.router.add_get('/diagram.js', diagram_script)
    app.router.add_get('/api/status', status)
    app.router.add_get('/api/config', config)
    app.router.add_get('/sip', sip_socket)
    app.on_cleanup.append(cleanup)
    return app


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=int, default=8740)
    args = p.parse_args()
    load_dotenv(ROOT / '.env')
    web.run_app(create_app(Jamie(args.port)), host='127.0.0.1', port=args.port, access_log=None)
