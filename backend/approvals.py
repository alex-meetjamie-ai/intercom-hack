"""Call-scoped employee decisions for the local, simulated intercom."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import secrets


class ApprovalDesk:
    def __init__(self, notify=None, timeout=40):
        self.timeout = timeout
        self.notify = notify or (lambda *args: None)
        self.requests = {}
        self.subscribers = set()

    def snapshot(self):
        return [deepcopy(item['public']) for item in self.requests.values()]

    def subscribe(self):
        queue = asyncio.Queue(maxsize=1)
        self.subscribers.add(queue)
        queue.put_nowait({'type': 'approvals', 'requests': self.snapshot()})
        return queue

    def publish(self):
        for queue in self.subscribers:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait({'type': 'approvals', 'requests': self.snapshot()})

    async def ask(self, owner, context):
        now = datetime.now(timezone.utc)
        request_id = secrets.token_urlsafe(16)
        public = {'id': request_id, 'status': 'pending', 'created_at': now.isoformat(),
                  'expires_at': (now + timedelta(seconds=self.timeout)).isoformat(), **deepcopy(context)}
        future = asyncio.get_running_loop().create_future()
        self.requests[request_id] = {'public': public, 'owner': owner, 'future': future}
        # Retain a short decision history, never remove an unanswered request.
        for key in list(self.requests):
            if len(self.requests) <= 20:
                break
            if self.requests[key]['public']['status'] != 'pending':
                del self.requests[key]
        self.notify('employee_approval', 'Waiting for employee approval · ' + context['name'], True,
                    {'approval': deepcopy(public)})
        self.publish()
        try:
            return await asyncio.wait_for(asyncio.shield(future), self.timeout)
        except asyncio.TimeoutError:
            self.finish(request_id, 'expired')
            return deepcopy(public)
        except asyncio.CancelledError:
            self.finish(request_id, 'cancelled')
            raise

    def finish(self, request_id, status):
        item = self.requests[request_id]
        public = item['public']
        if public['status'] != 'pending':
            return
        public.update(status=status, decided_at=datetime.now(timezone.utc).isoformat())
        if not item['future'].done():
            item['future'].set_result(deepcopy(public))
        labels = {'allowed': 'Employee allowed entry', 'denied': 'Employee denied entry',
                  'expired': 'Employee approval timed out — door stays closed',
                  'cancelled': 'Approval cancelled — call ended'}
        self.notify('employee_decision', labels[status] + ' · ' + public['name'], status == 'allowed',
                    {'approval': deepcopy(public)})
        self.publish()

    def decide(self, request_id, decision):
        if decision not in ('allow', 'deny'):
            raise ValueError('Choose Allow or Deny.')
        item = self.requests.get(request_id)
        if not item or item['public']['status'] != 'pending':
            raise ValueError('This request is no longer awaiting a decision.')
        if not item['owner'].active:
            self.finish(request_id, 'cancelled')
            raise ValueError('The call has ended. The door stays closed.')
        if datetime.now(timezone.utc) >= datetime.fromisoformat(item['public']['expires_at']):
            self.finish(request_id, 'expired')
            raise ValueError('This request expired. The door stays closed.')
        self.finish(request_id, 'allowed' if decision == 'allow' else 'denied')

    def cancel(self, owner):
        for key, item in list(self.requests.items()):
            if item['owner'] is owner:
                self.finish(key, 'cancelled')
