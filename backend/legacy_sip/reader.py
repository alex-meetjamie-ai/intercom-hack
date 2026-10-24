"""Experimental Access discovery/adoption/MQTT endpoint. Never operates a lock."""
import asyncio
import hashlib
import ipaddress
import json
import re
import secrets
import socket
import ssl
import time
from pathlib import Path
from aiohttp import web
import paho.mqtt.client as mqtt
import wire
import provisioning
from native_calls import NativeCalls, CallError
from ems_media import EmsMedia, settings as ems_settings
from security import load_state, save_state, make_cert, validate_adoption, broker_target, mqtt_context, private_write

KNOWN_RPC = {'/config/update', '/relay/unlock', '/test', '/stat', '/update_tokens', '/update_configs', '/remote_view', '/third_party_sip_call', '/update', '/delete', '/remote_open_door', '/call_admin_result', '/check_remote_call_state', '/check_is_remote_view_on', '/upgrade/install', '/remote_call_is_talked'}
KNOWN_HTTP = {'/api/v2/info', '/api/v2/adopt', '/api/v2/broker', '/api/v2/locate', '/api/v2/dev/verify', '/api/v2/get_configs', '/api/v2/doorbell', '/api/v2/ems_settings', '/api/v2/talkbacksettings'}


class Reader:
    def __init__(self, folder, ip='127.0.0.1', controller='127.0.0.1', port=8080, lab=True, emit=True):
        self.folder = Path(folder)
        self.state = load_state(folder)
        self.ip, self.controller, self.port, self.lab = ip, controller, port, lab
        self.started = int(time.time())
        self.monotonic = time.monotonic()
        self.emit = emit
        self.events = []
        self.mqtt_client = None
        self.mqtt_start_task = None
        self.stat_task = None
        self.runner = None
        self.discovery_transport = None
        self.queue_task = None
        self.queue = asyncio.Queue(maxsize=128)
        self.closed = False
        self.lock = asyncio.Lock()
        self.loop = None
        self.calls = NativeCalls(self)
        self.ems = EmsMedia(self)
        self.control_runner = None
        self.control_token = None
        self.bridge = None

    def call_lifecycle(self, action):
        if self.bridge:
            try:
                self.bridge.native_event(action)
            except (RuntimeError, ValueError):
                self.bridge.stop()
                self.event('bridge_call_state_failed')
                return False
        return True

    def event(self, name, **details):
        # All callers supply only sizes, booleans, codes or fixed allowlisted labels.
        record = {'time': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'event': name, **details}
        self.events.append(record)
        self.events = self.events[-500:]
        if self.emit:
            print(json.dumps(record), flush=True)

    def uptime(self):
        return int(time.monotonic() - self.monotonic)

    def info(self):
        a = self.state.get('adoption') or {}
        return {'id': self.state['id'], 'model': wire.MODEL, 'name': a.get('name', 'Access Software PoC'),
                'attrs': {'adopted': str(bool(a)).lower(), 'mac': ':'.join(self.state['id'][i:i+2] for i in range(0, 12, 2)),
                          'ipv4': self.ip, 'fw': wire.FW, 'app_ver': 'v3.14.4552',
                          'broker': a.get('broker_address', ''), 'revision': str(self.state.get('provisioning', {}).get('revision', 0)), 'uah_id': '',
                          'nacl_public_key': self.state['nacl_public'], 'updating': False}}

    @staticmethod
    def response(data=None, status=200, msg='success'):
        return web.json_response({'code': {200: 0, 401: 1, 400: 2, 404: 3}.get(status, status), 'msg': msg, 'data': data}, status=status)

    async def http(self, request):
        route = request.path if request.path in KNOWN_HTTP else 'unimplemented'
        if route == 'unimplemented':
            private_write(self.folder / 'last-unsupported-http.json', json.dumps({'method': request.method, 'path': request.path}))
        self.event('http_request', method=request.method, route=route)
        if request.remote != self.controller:
            return self.response(status=403, msg='Controller source required')
        a = self.state.get('adoption')
        credentials = [(a['ssh_user'], a['ssh_password'])] if a else [('ubnt', 'ubnt'), ('ui', 'ui')]
        if not wire.authorized(request.headers.get('Authorization', ''), credentials):
            self.event('http_auth_rejected', route=route)
            return self.response(status=401, msg='Not Authenticated')
        if request.method == 'GET' and request.path == '/api/v2/info':
            return self.response(self.info())
        if request.method == 'POST' and request.path == '/api/v2/adopt':
            async with self.lock:
                if self.state.get('adoption'):
                    return self.response(status=400, msg='Already adopted')
                try:
                    data = await request.json()
                    # Keep the controller's actual schema for interoperability
                    # debugging. This contains secrets and stays in private state.
                    private_write(self.folder / 'adoption-attempt.json', json.dumps(data))
                    validate_adoption(data, self.controller, self.lab)
                    candidate = dict(self.state)
                    extras = data.get('extras', {})
                    if extras.get('nacl_pub_key'):
                        candidate['nacl_public'] = extras['nacl_pub_key']
                        candidate['nacl_private'] = extras['nacl_priv_key']
                    # Keep only the adoption fields needed by this prototype.
                    keep = ('controller_id', 'controller_type', 'name', 'ssh_user', 'ssh_password', 'broker_address', 'broker_cert_ca', 'broker_cert', 'broker_priv_key')
                    candidate['adoption'] = {k: data[k] for k in keep if k in data}
                    candidate['adoption']['extras'] = {k: extras[k] for k in ('mqtt_cert_fingerprint', 'http_cert_fingerprint') if k in extras}
                    save_state(self.folder, candidate)
                    self.state = candidate
                except (ValueError, KeyError, TypeError, UnicodeError):
                    self.event('adoption_rejected', reason='schema_or_credentials')
                    return self.response(status=400, msg='Invalid adoption schema or credentials')
                self.event('adoption_saved', controller_keys_received=True)
                self.mqtt_start_task = asyncio.create_task(self.start_mqtt())
                return self.response(self.info())
        if a and request.method == 'GET' and request.path == '/api/v2/get_configs':
            return self.response(self.state.get('settings', {}))
        if a and request.method == 'GET' and request.path == '/api/v2/ems_settings':
            return self.response(ems_settings())
        if a and request.method == 'GET' and request.path == '/api/v2/talkbacksettings':
            return self.response(ems_settings()['talkbackSettings'])
        if a and request.method == 'POST' and request.path == '/api/v2/doorbell':
            try:
                await (self.bridge.ring() if self.bridge else self.calls.ring())
                return self.response()
            except Exception as exc:
                self.event('call_request_failed', error_type=type(exc).__name__)
                return self.response(status=400, msg='Call could not start')
        # Do not acknowledge success for an operation we did not implement.
        self.event('http_unsupported', route=route)
        return self.response(status=404, msg='Unsupported in software PoC')

    async def start_http(self):
        self.loop = asyncio.get_running_loop()
        app = web.Application(client_max_size=131072)
        app.router.add_route('*', '/{path:.*}', self.http)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        cert, key = make_cert(self.folder, self.ip)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(cert, key)
        site = web.TCPSite(self.runner, self.ip, self.port, ssl_context=ctx)
        await site.start()
        if self.port == 0:
            self.port = site._server.sockets[0].getsockname()[1]
        self.event('https_listening', port=self.port, loopback=ipaddress.ip_address(self.ip).is_loopback, device_id=self.state['id'], model=self.info()['model'])
        self.queue_task = asyncio.create_task(self.consume_mqtt())
        if self.state.get('adoption'):
            self.mqtt_start_task = asyncio.create_task(self.start_mqtt())

    def enqueue(self, item):
        if not self.closed:
            try:
                self.queue.put_nowait(item)
            except asyncio.QueueFull:
                self.event('mqtt_queue_full')

    async def start_mqtt(self):
        if self.closed or self.mqtt_client:
            return
        a = self.state['adoption']
        try:
            host, port, tls = broker_target(a['broker_address'], self.controller, self.lab)
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.state['id'], protocol=mqtt.MQTTv311, clean_session=True)
            if tls:
                client.tls_set_context(mqtt_context(self.folder, a))
            def on_connect(c, userdata, flags, reason, properties):
                ok = not reason.is_failure
                # Optional extra fingerprint check uses the authenticated TLS session.
                fingerprint = a.get('extras', {}).get('mqtt_cert_fingerprint', '').replace(':', '').lower()
                if ok and fingerprint:
                    if len(fingerprint) not in (40, 64) or not re.fullmatch('[0-9a-f]+', fingerprint):
                        ok = False
                    else:
                        peer = c.socket().getpeercert(binary_form=True)
                        digest = hashlib.sha256(peer).hexdigest() if len(fingerprint) == 64 else hashlib.sha1(peer).hexdigest()
                        ok = digest == fingerprint
                self.loop.call_soon_threadsafe(self.enqueue, ('connected', ok))
                if not ok:
                    c.disconnect()
            def on_message(c, userdata, msg):
                if len(msg.payload) <= 1048576:
                    self.loop.call_soon_threadsafe(self.enqueue, ('message', msg.topic, msg.payload))
            def on_disconnect(c, userdata, flags, reason, properties):
                self.loop.call_soon_threadsafe(self.enqueue, ('disconnected', reason.is_failure))
            def on_connect_fail(c, userdata):
                self.loop.call_soon_threadsafe(self.enqueue, ('connection_failed',))
            client.on_connect_fail = on_connect_fail
            client.on_connect, client.on_message, client.on_disconnect = on_connect, on_message, on_disconnect
            self.mqtt_client = client
            client.reconnect_delay_set(2, 30)
            client.connect_async(host, port, keepalive=30)
            client.loop_start()
            self.event('mqtt_connecting', tls=tls, port=port)
        except (ValueError, KeyError, OSError, ssl.SSLError):
            self.event('mqtt_setup_failed', reason='credentials_or_tls')
            self.mqtt_client = None

    def resource(self):
        return f"/uctrl/{self.state['adoption']['controller_id']}/device/{self.state['id']}"

    async def consume_mqtt(self):
        while True:
            item = await self.queue.get()
            if item[0] == 'connected':
                self.event('mqtt_connected' if item[1] else 'mqtt_rejected')
                if item[1]:
                    self.mqtt_client.subscribe(self.resource() + '/rpc/+/request', qos=0)
                    self.publish_stat()
                    if self.stat_task:
                        self.stat_task.cancel()
                    self.stat_task = asyncio.create_task(self.stat_loop())
            elif item[0] == 'connection_failed':
                self.event('mqtt_connection_failed', check='broker_reachability_and_certificate_trust')
            elif item[0] == 'disconnected':
                self.event('mqtt_disconnected', failure=item[1])
                self.call_lifecycle('transport_failed')
            elif item[0] == 'message':
                await self.handle_rpc(item[1], item[2])

    def device_stat(self):
        return wire.device_stat(self.state, self.ip, self.uptime())

    def publish_stat(self):
        if self.mqtt_client and self.mqtt_client.is_connected():
            payload = wire.message({}, self.device_stat())
            self.mqtt_client.publish(self.resource() + '/stat', payload, qos=0, retain=False)
            self.event('stat_sent', bytes=len(payload))

    async def stat_loop(self):
        while True:
            await asyncio.sleep(15)
            self.publish_stat()

    def rpc_reply(self, topic, packet):
        prefix = self.resource() + '/rpc/'
        if not topic.startswith(prefix):
            raise ValueError('wrong RPC scope')
        suffix = topic[len(prefix):].split('/')
        if len(suffix) != 2 or suffix[1] != 'request' or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', suffix[0]):
            raise ValueError('invalid RPC client')
        meta, body = wire.parse_message(packet)
        path = meta.get('path', '')
        request_id = meta.get('requestId', '')
        if len(request_id) > 256:
            raise ValueError('invalid request ID')
        tags = []
        try:
            tags = sorted(set(t for t, _ in wire.protobuf(body)))[:32]
        except ValueError:
            pass
        self.event('rpc_request', path=path if path in KNOWN_RPC else 'unimplemented', bytes=len(body), protobuf_tags=tags)
        code, error, response = -2, '404', b''
        if path == '/test':
            code, error, response = 0, '', b'hi'
        elif path == '/stat':
            code, error, response = 0, '', self.device_stat()
        elif path in ('/update_configs', '/update_tokens'):
            try:
                private_write(self.folder / ('last' + path.replace('/', '-') + '.pb'), body)
                candidate = (provisioning.apply_configs(self.state, body) if path == '/update_configs'
                             else provisioning.apply_tokens(self.state, body, self.controller, self.lab))
                save_state(self.folder, candidate)
                self.state = candidate
                code, error, response = 0, '', b'success'
                self.event('configuration_applied', operation=path, revision=candidate.get('provisioning', {}).get('revision', 0))
            except (ValueError, KeyError, TypeError, UnicodeError):
                code, error = 1, 'Invalid provisioning payload'
        elif path == '/check_remote_call_state':
            provisioning.decode('DACheckRemoteCallStateRequest', body)
            code, error, response = 0, '', b'success'
        elif path == '/check_is_remote_view_on':
            if self.calls.pc:
                code, error, response = 0, '', b'success'
            else:
                code, error = 100101, 'No running view session'
        elif path == '/remote_call_is_talked':
            self.event('call_picked_up')
            if self.call_lifecycle('answered'):
                code, error, response = 0, '', b'success'
            else:
                code, error = 1, 'Bridge audio is not available'
        # No lock actuation, firmware updates, or fabricated hardware verification.
        reply_meta = {'path': path, 'requestId': request_id, 'code': str(code), 'error': error}
        return topic[:-len('request')] + 'response', wire.message(reply_meta, response)

    async def handle_rpc(self, topic, packet):
        try:
            reply_topic, response = self.rpc_reply(topic, packet)
            meta, body = wire.parse_message(packet)
            path = meta.get('path')
            if path in ('/remote_view', '/call_admin_result'):
                code, error = 0, ''
                try:
                    private_write(self.folder / ('last' + path.replace('/', '-') + '.pb'), body)
                    if path == '/remote_view':
                        await self.calls.remote_view(provisioning.decode('DARemoteView', body))
                    else:
                        result = provisioning.decode('DACallAdminResult', body)
                        if result.get('response') in ('reject', 'rejected', 'cancel', 'timeout', 'hangup'):
                            await self.calls.hangup()
                        self.event('call_admin_result')
                except Exception as exc:
                    code, error = 1, 'Call operation failed'
                    self.event('call_operation_failed', error_type=type(exc).__name__,
                               reason=str(exc) if isinstance(exc, CallError) else 'transport_or_schema')
                response = wire.message({'path': path, 'requestId': meta.get('requestId', ''), 'code': str(code), 'error': error}, b'success' if not code else b'')
            self.mqtt_client.publish(reply_topic, response, qos=0, retain=False)
        except (ValueError, KeyError, TypeError, UnicodeError):
            self.event('mqtt_message_rejected', bytes=len(packet))

    def diagnostics(self):
        return self.bridge.status() if self.bridge else {}

    async def start_control(self):
        self.control_token = secrets.token_urlsafe(32)
        async def control(request):
            if request.remote != '127.0.0.1' or not secrets.compare_digest(request.headers.get('Authorization', ''), 'Bearer ' + self.control_token):
                return web.json_response({'error': 'Unauthorized'}, status=401)
            try:
                if request.method == 'POST' and request.path == '/ring':
                    result = await (self.bridge.ring() if self.bridge else self.calls.ring())
                elif request.method == 'POST' and request.path == '/hangup':
                    await (self.bridge.hangup() if self.bridge else self.calls.hangup())
                    result = self.calls.status()
                elif request.method == 'POST' and request.path == '/sks-answer' and self.bridge:
                    result = self.bridge.answer()
                elif request.method == 'POST' and request.path == '/sks-event' and self.bridge:
                    result = await self.bridge.input_event(await request.json())
                elif (request.method == 'POST' and request.path in ('/sim-pickup', '/sim-unlock')
                      and self.lab and getattr(self, 'lab_controls', None)):
                    result = self.lab_controls(request.path, await request.json())
                elif request.method == 'POST' and request.path == '/record' and self.bridge:
                    from audio_io import MacAudio
                    if not isinstance(self.ems.audio, MacAudio):
                        raise ValueError('Recording requires explicit Mac audio mode')
                    data = await request.json()
                    result = await self.ems.audio.record(data.get('seconds'),
                        Path(__file__).resolve().parent.parent / 'unifi-access-recordings')
                elif request.method == 'GET' and request.path == '/status':
                    result = {'device_id': self.state['id'], 'adopted': bool(self.state.get('adoption')),
                              **self.calls.status(), 'ems': self.ems.status(), **self.diagnostics()}
                else:
                    return web.json_response({'error': 'Not found'}, status=404)
                return web.json_response(result)
            except Exception as exc:
                self.event('local_call_failed', error_type=type(exc).__name__)
                return web.json_response({'error': str(exc) if isinstance(exc, CallError) else type(exc).__name__}, status=409)
        app = web.Application(client_max_size=1024)
        app.router.add_route('*', '/{path:.*}', control)
        self.control_runner = web.AppRunner(app, access_log=None)
        await self.control_runner.setup()
        site = web.TCPSite(self.control_runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        private_write(self.folder / 'control.json', json.dumps({'url': f'http://127.0.0.1:{port}', 'token': self.control_token}))
        self.event('local_control_ready', port=port)

    async def start_discovery(self):
        reader = self
        class Discovery(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                self.transport = transport
            def datagram_received(self, data, addr):
                if addr[0] != reader.controller:
                    return
                try:
                    version, cmd, fields = wire.parse_tlv(data)
                    reader.event('discovery_probe', version=version, command=cmd, tags=sorted(fields))
                    if version not in (1, 2) or cmd not in (0, 6) or fields:
                        return
                except ValueError:
                    return
                self.transport.sendto(reader.discovery_packet(), addr)
                reader.event('discovery_response')
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('0.0.0.0', 10001))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton('233.89.188.1') + socket.inet_aton(self.ip))
            sock.setblocking(False)
            self.discovery_transport, _ = await self.loop.create_datagram_endpoint(Discovery, sock=sock)
        except BaseException:
            sock.close()
            raise
        self.discovery_transport.sendto(self.discovery_packet(), (self.controller, 10001))
        self.event('discovery_enabled', unicast_announcement=True)

    def discovery_packet(self):
        return wire.discovery(self.state, self.ip, self.port, self.uptime(), self.started)

    async def close(self):
        self.closed = True
        if self.bridge:
            try:
                await self.bridge.close()
            except Exception as exc:
                self.event('bridge_shutdown_failed', error_type=type(exc).__name__)
        await self.ems.close()
        await self.calls.close()
        if self.control_runner:
            await self.control_runner.cleanup()
            (self.folder / 'control.json').unlink(missing_ok=True)
        tasks = [t for t in (self.stat_task, self.queue_task, self.mqtt_start_task) if t]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.discovery_transport:
            self.discovery_transport.close()
        if self.mqtt_client:
            self.mqtt_client.disconnect()
            await asyncio.to_thread(self.mqtt_client.loop_stop)
        if self.runner:
            await self.runner.cleanup()
        private_write(self.folder / 'events.json', json.dumps(self.events, indent=2))
