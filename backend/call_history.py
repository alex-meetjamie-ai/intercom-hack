"""Short-lived conversation context for this one simulated intercom."""
from collections import deque
from copy import deepcopy
from datetime import datetime, timedelta, timezone


class RecentCalls:
    def __init__(self, limit=5, minutes=30, clock=None):
        self.calls = deque(maxlen=limit)
        self.lifetime = timedelta(minutes=minutes)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def remember(self, visitor, transcript):
        decision = visitor.entry_decision or {}
        if not transcript and not decision:
            return
        self.calls.append({
            'ended_at': self.clock().isoformat(),
            'visitor_label': decision.get('name'),
            'personal_name': decision.get('personal_name'),
            'employee_decision': decision.get('status', 'not_requested'),
            # Employee Allow may be followed by a hangup/audio failure. Record
            # the actual effect separately so memory never invents an opening.
            'door_opened': visitor.admitted,
            'transcript': [{'speaker': m['speaker'], 'text': m['text'][:500]}
                           for m in list(transcript)[-12:]],
        })
        self.snapshot()

    def snapshot(self):
        cutoff = self.clock() - self.lifetime
        while self.calls and datetime.fromisoformat(self.calls[0]['ended_at']) <= cutoff:
            self.calls.popleft()
        return deepcopy(list(self.calls))
