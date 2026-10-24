"""Firmware-derived protobuf configuration, persisted atomically without actuation."""
import base64
import copy
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit
import wire

SCHEMAS = json.loads(Path(__file__).with_name('schemas.json').read_text())


def decode(name, packet, depth=0):
    if depth > 12:
        raise ValueError('protobuf nesting limit')
    schema = SCHEMAS[name]
    tags = {v['tag']: (k, v) for k, v in schema.items()}
    out = {}
    for tag, value in wire.protobuf(packet):
        if tag not in tags:
            continue
        key, desc = tags[tag]
        typ = desc['type']
        if typ in ('INT32', 'INT64', 'UINT32', 'UINT64', 'BOOL'):
            if not isinstance(value, int):
                raise ValueError('invalid scalar wire type')
            if typ == 'BOOL':
                if value not in (0, 1):
                    raise ValueError('invalid boolean')
                value = bool(value)
        else:
            if not isinstance(value, bytes):
                raise ValueError('invalid message wire type')
            if typ == 'STRING':
                value = value.decode('utf-8')
            elif typ in SCHEMAS:
                value = decode(typ, value, depth + 1)
            # Unknown nested types remain opaque and are retained in original wire bytes.
        if desc.get('repeated'):
            out.setdefault(key, []).append(value)
            if len(out[key]) > 4096:
                raise ValueError('repeated field limit')
        else:
            if key in out:
                raise ValueError('duplicate singular field')
            out[key] = value
    return out


def encode(name, data):
    fields = []
    for key, value in data.items():
        desc = SCHEMAS[name][key]
        for item in (value if desc.get('repeated') else [value]):
            tag, typ = desc['tag'], desc['type']
            if typ in ('INT32', 'INT64', 'UINT32', 'UINT64', 'BOOL'):
                fields.append(wire.varint(tag << 3) + wire.varint(int(item)))
            else:
                if typ in SCHEMAS:
                    item = encode(typ, item)
                fields.append(wire.field(tag, item))
    return b''.join(fields)


def scoped_url(url, controller, lab=False, websocket=False):
    u = urlsplit(url)
    schemes = ('wss',) if websocket else ('https',)
    if (u.scheme not in schemes or u.hostname != controller or u.username or u.password
            or u.fragment or not 1 <= (u.port or 443) <= 65535):
        raise ValueError('URL outside selected controller')
    if not lab and (u.port or 443) not in (443, 12443):
        raise ValueError('unapproved controller HTTP port')
    return url


def config_pairs(configs):
    if len(configs) > 512:
        raise ValueError('too many configuration entries')
    values = {}
    for entry in configs:
        k, v = entry.get('key'), entry.get('value')
        if not isinstance(k, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,96}', k) or not isinstance(v, str) or len(v) > 32768:
            raise ValueError('invalid configuration entry')
        if k in values:
            raise ValueError('duplicate configuration key')
        values[k] = v
    return values


def apply_configs(state, packet):
    data = decode('UpdateConfigs', packet)
    if set(data) != {'configs'}:
        raise ValueError('missing configs')
    result = copy.deepcopy(state)
    result.setdefault('settings', {}).update(config_pairs(data['configs']))
    return result


def apply_tokens(state, packet, controller, lab=False):
    data = decode('DAUpdate', packet)
    # Access 4.3.12 includes a download URL even when the full config is inline.
    # Only the explicit flag selects the external-payload path.
    if data.get('config_too_big'):
        raise ValueError('external provisioning payload not implemented')
    if not isinstance(data.get('revision'), int) or 'config' not in data:
        raise ValueError('missing configuration or revision')
    old_revision = state.get('provisioning', {}).get('revision', 0)
    if data['revision'] < old_revision and not data.get('force'):
        raise ValueError('stale provisioning revision')
    config = data['config']
    result = copy.deepcopy(state)
    result.setdefault('settings', {}).update(config_pairs(config.get('configs', [])))
    port = config.get('controller_port', 12443)
    host = config.get('controller_host', controller)
    origin = scoped_url(f'https://{host}:{port}', controller, lab)
    endpoints = {}
    for entry in config.get('api_endpoint', []):
        key, value = entry.get('key'), entry.get('value')
        if key in ('remote_call', 'ice_credentials', 'remote_app'):
            if not isinstance(value, str) or not value.startswith('/api/') or value.startswith('//') or len(value) > 512:
                raise ValueError('invalid provisioned endpoint')
            endpoints[key] = scoped_url(origin + value, controller, lab)
    location = config.get('location', {})
    # Preserve the whole update privately, including tokens, for reconnect/revision
    # fidelity. Tokens are never matched against a credential, logged, or used to unlock.
    result['provisioning'] = {
        'revision': data['revision'], 'updated_at': int(time.time()),
        'wire_base64': base64.b64encode(packet).decode(),
        'origin': origin, 'endpoints': endpoints,
        'access_token': config.get('access_token', ''),
        'door_name': config.get('door_name', ''), 'in_or_out': config.get('door_entry_method', 'in'),
        'location': location, 'token_count': len(data.get('tokens', [])),
    }
    return result
