#!/usr/bin/env python3
"""Safe defaults: no command means help; local mode binds loopback only."""
import argparse
import asyncio
import json
import re
import signal
import sys
from urllib.parse import urlsplit
from aiohttp import ClientError, ClientSession, ClientTimeout
import socket
import subprocess
from pathlib import Path
from reader import Reader

OFFICE_IP = '192.168.1.1'
OFFICE_MAC = '74:fa:29:5d:a8:87'


def office_identity():
    route = subprocess.run(['/sbin/route', '-n', 'get', OFFICE_IP], text=True, capture_output=True, check=True).stdout
    interface = re.search(r'interface:\s*(\S+)', route)
    if not interface or interface[1].startswith(('utun', 'tun', 'ppp')):
        raise RuntimeError('Office must be directly connected, not reached through a VPN')
    arp = subprocess.run(['/usr/sbin/arp', '-n', OFFICE_IP], text=True, capture_output=True).stdout
    match = re.search(r' at ([0-9a-fA-F:]+) ', arp)
    mac = ':'.join(x.zfill(2) for x in match[1].lower().split(':')) if match else ''
    if mac != OFFICE_MAC:
        raise RuntimeError('Office gateway identity not found; no emulator traffic sent. At the office, open the local console first and retry.')
    result = subprocess.run(['/usr/sbin/ipconfig', 'getifaddr', interface[1]], text=True, capture_output=True, check=True)
    ip = result.stdout.strip()
    if not re.fullmatch(r'192\.168\.1\.(?:[1-9][0-9]{0,2})', ip) or ip == OFFICE_IP:
        raise RuntimeError('Unexpected office interface address')
    return ip


async def preflight(ip):
    results = {}
    for port in (12443, 12812, 12442):
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(OFFICE_IP, port), 2)
            writer.close(); await writer.wait_closed()
            results[str(port)] = 'reachable'
        except (OSError, asyncio.TimeoutError):
            results[str(port)] = 'unavailable'
    print(json.dumps({'office_identity': 'matched', 'mac_ip': ip, 'ports': results}, indent=2))
    return results


async def serve(args):
    if args.command == 'office':
        ip = office_identity()
        status = await preflight(ip)
        if status['12443'] != 'reachable' or status['12812'] != 'reachable':
            raise RuntimeError('Access HTTPS/MQTT is not reachable. Verify Access is installed and running before testing adoption.')
        controller, lab = OFFICE_IP, False
    else:
        ip = controller = '127.0.0.1'; lab = True
    folder = Path(args.state or ('.state-lab' if lab else '.state-office-access'))
    reader = Reader(folder, ip=ip, controller=controller, lab=lab)
    try:
        await reader.start_http()
        await reader.start_control()
        if not lab:
            await reader.start_discovery()
        if getattr(args, 'ems', False):
            if lab:
                raise ValueError('--ems requires the guarded office command')
            await reader.ems.start()
        print('Software reader running. Ring and hangup controls are ready after provisioning. Audio source: test tone; SKS hardware is not connected.', flush=True)
        done = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig, done.set)
        try:
            await asyncio.wait_for(done.wait(), timeout=args.minutes * 60)
        except asyncio.TimeoutError:
            pass
    finally:
        await reader.close()
        print('Stopped all prototype listeners.', flush=True)


async def control(args):
    path = Path(args.state) / 'control.json'
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise RuntimeError('Control credentials must be a private regular file')
    data = json.loads(path.read_text())
    url = urlsplit(data['url'])
    if url.scheme != 'http' or url.hostname != '127.0.0.1' or url.username or url.password or url.path or url.query or url.fragment:
        raise RuntimeError('Invalid local control address')
    payload = None
    if args.command == 'record':
        payload = {'seconds': args.seconds}
    elif args.command == 'sks-event':
        payload = {'event': args.event}
        if args.call_id is not None:
            payload['call_id'] = args.call_id
    elif args.command == 'sim-pickup':
        payload = {'call_id': args.call_id}
    elif args.command == 'sim-unlock':
        payload = {'request_id': args.request_id}
    async with ClientSession(timeout=ClientTimeout(total=35), trust_env=False) as client:
        async with client.request('GET' if args.command == 'status' else 'POST', data['url'] + '/' + args.command,
                                  json=payload,
                                  headers={'Authorization': 'Bearer ' + data['token']}, allow_redirects=False) as response:
            result = await response.json()
            print(json.dumps(result, indent=2))
            if response.status != 200:
                raise RuntimeError('Local command did not complete')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command')
    for command in ('local', 'office'):
        p = sub.add_parser(command)
        p.add_argument('--state')
        p.add_argument('--minutes', type=float, default=20)
        if command == 'office':
            p.add_argument('--ems', action='store_true', help='Start generated media ingest and talkback counters (already adopted reader)')
    sub.add_parser('preflight')
    sub.add_parser('selftest')
    p = sub.add_parser('sks-lab', help='Run isolated SKS simulation; no office or microphone access')
    p.add_argument('--state', default='.state-sks-lab')
    p.add_argument('--minutes', type=float, default=10)
    p = sub.add_parser('sks-scenarios', help='Run offline adapter scenarios and save their outcomes')
    p.add_argument('--output', default='sks-simulation-results.json')
    for command in ('ring', 'hangup', 'status', 'sks-answer', 'record', 'sks-event', 'sim-pickup', 'sim-unlock'):
        p = sub.add_parser(command)
        p.add_argument('--state', default=('.state-sks-lab/reader' if command in
                       ('sks-event', 'sim-pickup', 'sim-unlock') else '.state-office-access'))
        if command == 'record':
            p.add_argument('--seconds', type=int, choices=range(1, 31), default=10, metavar='1..30')
        elif command == 'sks-event':
            from sks_adapter import INPUT_EVENTS
            p.add_argument('event', choices=INPUT_EVENTS)
            p.add_argument('--call-id')
        elif command == 'sim-pickup':
            p.add_argument('--call-id', required=True)
        elif command == 'sim-unlock':
            p.add_argument('--request-id', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'selftest':
            result = subprocess.run([sys.executable, '-m', 'unittest', '-v'], cwd=Path(__file__).parent)
            raise SystemExit(result.returncode)
        elif args.command in ('ring', 'hangup', 'status', 'sks-answer', 'record', 'sks-event', 'sim-pickup', 'sim-unlock'):
            asyncio.run(control(args))
        elif args.command == 'sks-scenarios':
            from sks_lab import run_scenarios
            result = asyncio.run(run_scenarios())
            Path(args.output).write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps({'result': str(Path(args.output).resolve()), 'passed': len(result['scenarios'])}))
        elif args.command == 'sks-lab':
            if not 0 < args.minutes <= 120:
                parser.error('--minutes must be between 0 and 120')
            from sks_lab import serve
            asyncio.run(serve(args))
        elif args.command == 'preflight':
            asyncio.run(preflight(office_identity()))
        elif args.command:
            if not 0 < args.minutes <= 120:
                parser.error('--minutes must be between 0 and 120')
            asyncio.run(serve(args))
        else:
            parser.print_help()
    except (RuntimeError, OSError, ValueError, ClientError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
