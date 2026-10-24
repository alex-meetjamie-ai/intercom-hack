"""In-memory door only. There is no physical unlock implementation."""
import asyncio
from collections import deque
from copy import deepcopy
import json
import re

from arrivals import lookup
from elevator import Elevator
from approvals import ApprovalDesk


class Door:
    def __init__(self, seconds=5):
        self.seconds = seconds
        self.open = False
        self.timer = None

    def unlock(self):
        self.close()
        self.open = True
        self.timer = asyncio.get_running_loop().call_later(self.seconds, self.close)

    def close(self):
        self.open = False
        if self.timer:
            self.timer.cancel()
            self.timer = None


class Visitor:
    def __init__(self, door, elevator=None, notify=None, approvals=None):
        self.door = door
        self.elevator = elevator if elevator is not None else Elevator()
        self.notify = notify or (lambda tool, message, ok, evidence: None)
        self.name = None
        self.active = True
        self.results = {}
        self.heard = deque(maxlen=20)
        self.approved = {}
        self.admitted = False
        self.admission = asyncio.Event()
        self.approvals = approvals if approvals is not None else ApprovalDesk(self.notify)
        self.entry_decision = None
        self.tool_lock = asyncio.Lock()

    def hear(self, text):
        # A second, conservative check on ASR text, independent of the LLM's
        # tool arguments. This is self-identification, not identity verification.
        text = text.casefold().replace('’', "'").strip()
        self.heard.append(text[:2000])
        if re.search(r"\b(?:not|isn't|is not)\s+alex\b|\balex's\b", text):
            self.name = None
            return
        if re.fullmatch(r"alex[.!?, ]*", text):
            self.name = 'alex'
            return
        match = re.search(r"\b(?:my name is|i am|i'm|this is|it's)\s+([a-z]+)\b", text)
        if match:
            self.name = match.group(1)

    async def tool(self, call_id, name, parameters):
        # Serialize tool effects while leaving the audio/WebSocket receiver free.
        # Replayed IDs reuse the result, including a pending employee decision.
        async with self.tool_lock:
            return await self.run_tool(call_id, name, parameters)

    async def run_tool(self, call_id, name, parameters):
        if call_id in self.results:
            return self.results[call_id]
        evidence = {'arguments': deepcopy(parameters), 'heard': list(self.heard)}
        try:
            if not self.active or not isinstance(parameters, dict):
                raise ValueError('Tool requires an active call and valid arguments.')
            result, summary, details = await self.dispatch(name, parameters)
            evidence.update(details)
            evidence['output'] = deepcopy(result)
            result = {'is_error': False, 'result': result if isinstance(result, str) else json.dumps(result)}
        except ValueError as exc:
            result = {'is_error': True, 'result': str(exc)}
            summary = str(exc)
            evidence['output'] = str(exc)
        self.results[call_id] = result
        self.notify(name, summary, not result['is_error'], evidence)
        if name == 'open_door' and not result['is_error']:
            self.admission.set()
        return result

    async def dispatch(self, name, parameters):
        if name == 'check_calendar_emails':
            query = parameters.get('query')
            if set(parameters) != {'query'} or not isinstance(query, str) or not 1 <= len(query.strip()) <= 500:
                raise ValueError('Provide a short query using the visitor’s stated name, company and reason.')
            records = lookup(query, ' '.join(self.heard))
            self.approved = {record['id']: record for record in records}
            summary = ('Matched: ' + '; '.join(record['title'] for record in records)) if records else 'No matching visitor or delivery in the mock emails/calendar.'
            return {'mock': True, 'time_checks': False, 'can_enter': False, 'record_match': bool(records),
                    'employee_approval_required': True, 'matches': records,
                    'instruction': 'Ignore arrival time. Call open_door to request employee approval; include a returned match_id if available. A record match never authorizes entry on its own.'}, summary, {'matched_records': records}
        if name == 'open_door':
            claimed_name = parameters.get('name')
            match_id = parameters.get('match_id')
            if (not set(parameters).issubset({'name', 'match_id'}) or not isinstance(claimed_name, str)
                    or not claimed_name.strip() or len(claimed_name) > 200
                    or (match_id is not None and not isinstance(match_id, str))):
                raise ValueError('Provide the visitor name and, for an expected arrival, its lookup match_id.')
            alex = claimed_name.strip().casefold() == 'alex' and self.name == 'alex'
            if match_id is not None and match_id not in self.approved:
                raise ValueError('The match_id must come from this call’s lookup. Omit it if there was no match.')
            if self.entry_decision is not None:
                raise ValueError('This call already has an employee decision. Do not repeat the unlock request.')
            records = [self.approved[match_id]] if match_id else []
            decision = await self.approvals.ask(self, {'name': claimed_name.strip(),
                'heard': list(self.heard), 'matched_records': records, 'alex_claim': alex})
            self.entry_decision = decision
            if not self.active or decision['status'] != 'allowed':
                raise ValueError('Door remains closed. Employee decision: ' + decision['status'] + '. Do not retry in this call.')
            self.door.unlock()
            self.admitted = True
            reason = claimed_name.strip() + ' · employee approved'
            return ('The simulated door is open. It closes automatically in five seconds.', 'Door opened · ' + reason,
                    {'basis': 'employee_approval', 'approval': decision, 'matched_records': records})
        if name == 'send_elevator':
            if set(parameters) != {'floor'}:
                raise ValueError('Provide only the destination floor.')
            if not self.admitted:
                raise ValueError('Admit the visitor with open_door before sending the elevator.')
            state = self.elevator.send(parameters['floor'])
            summary = 'Elevator sent to floor ' + state['label']
            if state['floor'] == 0:
                summary += ' · returns to 5 after 10 seconds on floor 0'
            return state, summary, {}
        raise ValueError('Unknown tool. Available: open_door, send_elevator, check_calendar_emails.')

    def close(self):
        self.active = False
        self.approvals.cancel(self)
        # A successful admission ends the call immediately, but the five-second
        # unlock pulse must still run to completion so the visitor can enter.
        if not self.admitted:
            self.door.close()
