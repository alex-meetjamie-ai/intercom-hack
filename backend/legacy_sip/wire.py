"""Observed G3 Reader Pro wire formats; see RESEARCH.md for provenance."""
import hashlib
import hmac
import ipaddress
import struct
import uuid

MODEL = 'UA-G3-Pro'
GUID = '3ea175ec-b901-25d4-c0c3-e21573850acd'
VERSION = 'v1.14.22'
FW = 'DA.qca805x.v1.14.22.0.000000.20260330.164414'


def auth_token(user, password, nonce='poc01'):
    # Firmware: nonce (5 chars) + MD5(user + MD5(password) + nonce).
    md5 = lambda s: hashlib.md5(s.encode(), usedforsecurity=False).hexdigest()
    if len(nonce) != 5:
        raise ValueError('nonce must have five characters')
    return nonce + md5(user + md5(password) + nonce)


def authorized(header, credentials):
    if not header.startswith('Bearer '):
        return False
    token = header[7:]
    return len(token) == 37 and any(hmac.compare_digest(token, auth_token(u, p, token[:5])) for u, p in credentials)


def tlv_packet(fields, version=1, command=0):
    body = b''.join(struct.pack('!BH', tag, len(value)) + value for tag, value in fields.items())
    return struct.pack('!BBH', version, command, len(body)) + body


def parse_tlv(data):
    if not 4 <= len(data) <= 65539:
        raise ValueError('invalid discovery size')
    version, command, size = struct.unpack('!BBH', data[:4])
    if size != len(data) - 4:
        raise ValueError('invalid discovery length')
    fields, pos = {}, 4
    while pos < len(data):
        if pos + 3 > len(data):
            raise ValueError('truncated TLV header')
        tag, length = struct.unpack('!BH', data[pos:pos + 3])
        pos += 3
        if pos + length > len(data) or tag in fields:
            raise ValueError('truncated or duplicate TLV')
        fields[tag] = data[pos:pos + length]
        pos += length
    return version, command, fields


def discovery(state, ip, port, uptime, started):
    mac = bytes.fromhex(state['id'])
    fields = {
        2: mac + ipaddress.IPv4Address(ip).packed,
        3: FW.encode(), 10: struct.pack('!Q', uptime),
        11: b'Access Software PoC', 12: b'UA-G3-Pro',
        21: MODEL.encode(), 22: VERSION.encode(),
        23: bytes([0 if state.get('adoption') else 1]),  # INVERTED in firmware
        33: state['id'].encode(), 36: struct.pack('!I', port),
        39: struct.pack('!Q', started), 40: b'', 42: b'user',
        43: uuid.UUID(GUID).bytes,
        # No device attestation: report this honestly, never copy vendor keys.
        44: b'\x00', 45: struct.pack('!Q', started), 46: b'EA',
    }
    return tlv_packet(fields)


def varint(n):
    if not 0 <= n < 2**64:
        raise ValueError('invalid varint')
    out = bytearray()
    while n > 127:
        out.append((n & 127) | 128)
        n >>= 7
    out.append(n)
    return bytes(out)


def field(tag, value):
    if isinstance(value, str):
        value = value.encode()
    return varint((tag << 3) | 2) + varint(len(value)) + value


def protobuf(data):
    if len(data) > 1048576:
        raise ValueError('protobuf too large')
    pos = 0
    def read_varint():
        nonlocal pos
        n = 0
        for shift in range(0, 70, 7):
            if pos >= len(data):
                raise ValueError('truncated varint')
            b = data[pos]; pos += 1
            n |= (b & 127) << shift
            if b < 128:
                if n >= 2**64:
                    raise ValueError('varint overflow')
                return n
        raise ValueError('varint overflow')
    out = []
    while pos < len(data):
        key = read_varint(); tag, kind = key >> 3, key & 7
        if not tag:
            raise ValueError('zero protobuf tag')
        if kind == 0:
            value = read_varint()
        elif kind in (1, 2, 5):
            size = read_varint() if kind == 2 else (8 if kind == 1 else 4)
            if pos + size > len(data):
                raise ValueError('truncated protobuf')
            value = data[pos:pos + size]; pos += size
        else:
            raise ValueError('unsupported protobuf wire type')
        out.append((tag, value))
    return out


def message(meta, payload=b''):
    return b''.join(field(1, field(1, k) + field(2, str(v))) for k, v in meta.items()) + field(2, payload)


def parse_message(data):
    meta, payload = {}, b''
    for tag, value in protobuf(data):
        if tag == 1:
            entry = dict(protobuf(value))
            key, val = entry[1].decode(), entry[2].decode()
            if key in meta:
                raise ValueError('duplicate metadata')
            meta[key] = val
        elif tag == 2:
            payload = value
    return meta, payload


def device_stat(state, ip, uptime):
    a = state.get('adoption') or {}
    attrs = {
        'adopted': str(bool(a)).lower(), 'mac': ':'.join(state['id'][i:i+2] for i in range(0, 12, 2)),
        'ipv4': ip, 'fw': FW, 'app_ver': 'v3.14.4552', 'broker': a.get('broker_address', ''),
        'controller_id': a.get('controller_id', ''), 'proto_version': '1', 'port': '8080',
        'guid': GUID, 'uptime': str(uptime), 'revision': str(state.get('provisioning', {}).get('revision', 0)),
        'security_check': 'false', 'hw_type': 'EA', 'mode': 'user', 'device_capability': '0x00000002',
        'nacl_public_key': state['nacl_public'],
    }
    return (field(1, state['id']) + field(2, MODEL) + field(3, a.get('name', 'Access Software PoC'))
            + b''.join(field(4, f'{k}={v}') for k, v in attrs.items()))
