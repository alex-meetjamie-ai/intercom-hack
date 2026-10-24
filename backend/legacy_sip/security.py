"""Local credentials and explicit controller scope. No firmware private keys."""
import base64
import datetime
import ipaddress
import json
import os
import re
import ssl
from pathlib import Path
from urllib.parse import urlsplit
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from nacl.public import PrivateKey


def private_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.is_symlink():
        raise ValueError('state path cannot be a symlink')
    temp = path.with_name(path.name + '.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data.encode() if isinstance(data, str) else data)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def save_state(folder, state):
    private_write(Path(folder) / 'state.json', json.dumps(state))


def load_state(folder):
    p = Path(folder) / 'state.json'
    if p.exists():
        if p.is_symlink() or p.stat().st_mode & 0o077:
            raise ValueError('private state must be a regular 0600 file')
        return json.loads(p.read_text())
    key = PrivateKey.generate()
    mac = bytes([0x02]) + os.urandom(5)
    state = {'id': mac.hex(), 'nacl_public': base64.b64encode(bytes(key.public_key)).decode(),
             'nacl_private': base64.b64encode(bytes(key)).decode(), 'adoption': None}
    save_state(folder, state)
    return state


def make_cert(folder, ip, name='Access Software PoC'):
    folder = Path(folder)
    certfile, keyfile = folder / 'server.crt', folder / 'server.key'
    if certfile.exists() and keyfile.exists():
        return certfile, keyfile
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True).sign(key, hashes.SHA256()))
    private_write(keyfile, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    private_write(certfile, cert.public_bytes(serialization.Encoding.PEM))
    return certfile, keyfile


def broker_target(address, controller, lab=False):
    u = urlsplit(address)
    if u.hostname != controller or u.username or u.password or u.path not in ('', '/') or u.query or u.fragment:
        raise ValueError('broker must point only to the selected controller')
    if u.scheme not in ('ssl', 'mqtts', 'tls'):
        if not (lab and u.scheme in ('tcp', 'mqtt') and ipaddress.ip_address(controller).is_loopback):
            raise ValueError('broker TLS required')
    port = u.port or 12812
    if not lab and port != 12812:
        raise ValueError('unexpected office broker port')
    return u.hostname, port, u.scheme in ('ssl', 'mqtts', 'tls')


def validate_adoption(data, controller, lab=False):
    required = ('controller_id', 'name', 'ssh_user', 'ssh_password', 'broker_address')
    if not isinstance(data, dict) or any(not isinstance(data.get(k), str) or not data[k] for k in required):
        raise ValueError('adoption fields missing')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', data['controller_id']):
        raise ValueError('invalid controller ID')
    _, _, tls = broker_target(data['broker_address'], controller, lab)
    extras = data.get('extras', {})
    if not isinstance(extras, dict):
        raise ValueError('invalid extras')
    if tls:
        for k in ('broker_cert_ca', 'broker_cert'):
            x509.load_pem_x509_certificate(data[k].encode())
        key = serialization.load_pem_private_key(data['broker_priv_key'].encode(), None)
        cert = x509.load_pem_x509_certificate(data['broker_cert'].encode())
        fmt = serialization.PublicFormat.SubjectPublicKeyInfo
        if key.public_key().public_bytes(serialization.Encoding.DER, fmt) != cert.public_key().public_bytes(serialization.Encoding.DER, fmt):
            raise ValueError('client certificate/key mismatch')
    pub, priv = extras.get('nacl_pub_key'), extras.get('nacl_priv_key')
    if bool(pub) != bool(priv):
        raise ValueError('incomplete NaCl key pair')
    if pub:
        key = PrivateKey(base64.b64decode(priv, validate=True))
        if bytes(key.public_key) != base64.b64decode(pub, validate=True):
            raise ValueError('NaCl key mismatch')
    return data


def mqtt_context(folder, adoption):
    folder = Path(folder)
    for field, filename in [('broker_cert_ca', 'broker-ca.crt'), ('broker_cert', 'broker-client.crt'), ('broker_priv_key', 'broker-client.key')]:
        private_write(folder / filename, adoption[field])
    ctx = ssl.create_default_context(cafile=str(folder / 'broker-ca.crt'))
    # Controller-issued private CA authenticates the endpoint; these device certs
    # may lack IP SANs. Never disable CA verification.
    ctx.check_hostname = False
    ctx.load_cert_chain(folder / 'broker-client.crt', folder / 'broker-client.key')
    return ctx
