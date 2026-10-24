"""Distinct floors 0, E and 1–5; auto-return only after dwelling on 0."""
import asyncio
import math


class Elevator:
    def __init__(self, return_seconds=10, notify=None):
        self.floor = 5
        self.return_seconds = return_seconds
        self.notify = notify or (lambda message: None)
        self.timer = None
        self.return_at = None

    def send(self, floor):
        # E is a separate stop from numeric 0; booleans are not floors.
        if type(floor) not in (str, int):
            raise ValueError('Choose floor E, 0, 1, 2, 3, 4 or 5.')
        value = str(floor).strip().upper()
        if value not in ('E', '0', '1', '2', '3', '4', '5'):
            raise ValueError('Choose floor E, 0, 1, 2, 3, 4 or 5.')
        target = 'E' if value == 'E' else int(value)
        if target != self.floor:
            self.close()
            self.floor = target
        if target == 0 and self.timer is None:
            loop = asyncio.get_running_loop()
            self.return_at = loop.time() + self.return_seconds
            self.timer = loop.call_later(self.return_seconds, self.return_home)
        return self.status()

    def return_home(self):
        self.floor = 5
        self.timer = self.return_at = None
        self.notify(f'Elevator returned to floor 5 after {self.return_seconds:g} seconds on floor 0.')

    def status(self):
        remaining = None if self.return_at is None else max(0, math.ceil(
            self.return_at - asyncio.get_running_loop().time()))
        return {'floor': self.floor, 'label': str(self.floor),
                'return_in_seconds': remaining, 'simulated': True}

    def close(self):
        if self.timer:
            self.timer.cancel()
        self.timer = self.return_at = None
