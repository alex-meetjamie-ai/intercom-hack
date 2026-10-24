"""Logical indoor-station adapter simulator, not an SKS bus implementation.

Commands describe intent only: no GPIO, contact wiring, bus frames or voltage
levels are implied. A future physical driver must confirm each command before
the bridge reports it successful. Times are configurable manual-based models.
"""
import math
import re
import time
from collections import deque


INPUT_EVENTS = ('door-call', 'floor-call', 'internal-call', 'other-tenant', 'visitor-left',
                'line-lost', 'line-restored', 'fail-next-answer', 'fail-next-release')


def validate_event(data):
    if not isinstance(data, dict) or set(data) - {'event', 'call_id'}:
        raise ValueError('Expected event and optional call_id only')
    event, call_id = data.get('event'), data.get('call_id')
    if event not in INPUT_EVENTS:
        raise ValueError('Unknown simulated adapter event')
    if event in ('door-call', 'visitor-left'):
        if not isinstance(call_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', call_id):
            raise ValueError('This event needs a 1..64 character call_id')
    elif call_id is not None:
        raise ValueError('This event does not accept call_id')
    return event, call_id


class SimulatedSks:
    def __init__(self, window=120, clock=time.monotonic, after_release=10):
        if (not math.isfinite(window) or not 0 < window <= 150 or
                not math.isfinite(after_release) or not 0 < after_release <= 30):
            raise ValueError('Invalid simulated call or post-release duration')
        self.window, self.clock, self.after_release = window, clock, after_release
        self.state, self.call_id = 'idle', None
        self.deadline = 0.0
        self.generation = self.releases = 0
        self.relay = False
        self.online = True
        self.failure = None
        self.requests, self.calls = {}, {}
        self.journal = deque(maxlen=128)
        self.sequence = 0
        self.started = clock()
        self.note('ready')

    def note(self, event, **details):
        self.sequence += 1
        self.journal.append({'sequence': self.sequence,
                             'elapsed_ms': round((self.clock() - self.started) * 1000),
                             'event': event, 'call_number': self.generation, **details})

    def is_live(self):
        return self.online and self.state != 'idle' and self.clock() < self.deadline

    def ring(self, call_id=None):
        if not self.online:
            raise ValueError('Simulated SKS link is offline')
        self.calls = {key: at for key, at in self.calls.items() if self.clock() - at <= 300}
        if self.is_live() or (call_id is not None and call_id in self.calls):
            self.note('ring_ignored', reason='busy_or_duplicate')
            return False
        if len(self.calls) >= 128:
            raise ValueError('Too many simulated call IDs')
        self.end('replaced')
        self.generation += 1
        self.call_id = call_id or f'simulated-{self.generation}'
        self.calls[self.call_id] = self.clock()
        self.state, self.deadline = 'ringing', self.clock() + self.window
        self.note('entrance_call')
        return True

    def command(self, name):
        if not self.online:
            raise ValueError('Simulated SKS link is offline')
        if self.failure == name:
            self.failure = None
            self.online = False
            self.note('command_failed', command=name)
            raise ValueError('Simulated station did not acknowledge command')
        self.note('command_acknowledged', command=name)

    def answer(self, call_id=None):
        if not self.is_live() or (call_id is not None and call_id != self.call_id):
            raise ValueError('No matching current simulated SKS call')
        if self.state == 'answered':
            return False
        self.command('answer')
        self.state = 'answered'
        return True

    def release(self, request_id):
        if not self.is_live():
            raise ValueError('SKS unlock window is closed')
        if not isinstance(request_id, str) or not 0 < len(request_id) <= 256:
            raise ValueError('An unlock request ID is required')
        self.requests = {key: at for key, at in self.requests.items() if self.clock() - at <= 300}
        if request_id in self.requests:
            self.note('release_ignored', reason='duplicate_request')
            return False
        if len(self.requests) >= 128:
            raise ValueError('Too many unlock requests')
        # Record even coalesced requests so retrying later cannot create a pulse.
        self.requests[request_id] = self.clock()
        if self.relay:
            self.note('release_ignored', reason='pulse_already_active')
            return False
        self.command('door_release')
        self.releases += 1
        self.relay = True
        if self.state == 'answered':
            self.deadline = min(self.deadline, self.clock() + self.after_release)
        return True

    def relock(self):
        if self.relay:
            self.note('virtual_release_finished')
        self.relay = False

    def end(self, reason='hangup', notify_station=True):
        if self.state != 'idle':
            if self.state == 'answered' and self.online and notify_station:
                self.command('hangup')
            self.note('call_ended', reason=reason)
        self.state, self.call_id, self.deadline, self.relay = 'idle', None, 0.0, False

    def disconnect(self):
        self.online = False
        self.note('line_lost')

    def reconnect(self):
        self.end('line_restored', notify_station=False)
        self.online, self.failure = True, None
        self.note('line_restored')

    def status(self):
        return {'backend': 'simulated_sks', 'state': self.state, 'online': self.online,
                'call_id': self.call_id, 'call_number': self.generation,
                'release_count': self.releases,
                'unlock_window_remaining': round(max(0, self.deadline - self.clock()), 1),
                'relay': 'unlocked' if self.relay else 'locked',
                'door_position': 'unknown', 'physical_actuation': False,
                'pending_failure': self.failure, 'events': list(self.journal)}
