"""SKS call simulator and bridge coordinator. No bus driver, GPIO or real lock.

The 120-second window is a configurable test model, not a measurement of the
installed SKS unit. Its electrical interface is deliberately still absent.
"""
import asyncio
from sks_adapter import SimulatedSks, validate_event


class SksBridge:
    def __init__(self, reader, hub, audio, window=120, adapter=None, after_release=10):
        self.reader, self.hub, self.audio = reader, hub, audio
        self.adapter = adapter if adapter is not None else SimulatedSks(window, after_release=after_release)
        self.timer = None
        self.cleanup_tasks = set()
        self.closed = False
        self.lock = asyncio.Lock()
        self.reader.bridge = self
        self.hub.unlock_adapter = self
        self.hub.linked_bridge = self
        self.reader.ems.audio = audio

    async def ring(self, call_id=None):
        async with self.lock:
            if self.closed:
                raise ValueError('Bridge is closed')
            if self.cleanup_tasks:
                await asyncio.gather(*tuple(self.cleanup_tasks))
            if not self.adapter.ring(call_id):
                return {'ring_started': False, **self.status()}
            self.audio.set_active(False)
            self._arm_timer()
            self.reader.event('sks_simulated_ring', call_number=self.adapter.generation)
            try:
                await self.reader.calls.ring()
                if not self.adapter.is_live():
                    raise ValueError('Simulated call ended before ringing completed')
            except BaseException:
                self.stop()
                # Expiry/hangup can race a slow controller call request. Tear
                # down any session that completed after our window closed.
                await self.reader.calls.hangup()
                raise
            return {'ring_started': True, **self.status()}

    def answer(self, call_id=None):
        if call_id is not None and call_id != self.adapter.call_id:
            raise ValueError('Pickup belongs to a different simulated call')
        try:
            self.adapter.answer(call_id)
            if not self.audio.active:
                self.reader.ems.playback_codec = None
            self.audio.set_active(True)
        except Exception:
            self.stop('answer_failed')
            self._schedule_hangup()
            raise
        self.reader.event('sks_simulated_answer')
        return self.status()

    def release(self, request_id):
        try:
            changed = self.adapter.release(request_id)
        except ValueError:
            if not self.adapter.online:
                self.stop('adapter_command_failed')
                self._schedule_hangup()
            raise
        if changed:
            self._arm_timer()
        return changed

    def relock(self):
        self.adapter.relock()

    def _arm_timer(self):
        if self.timer:
            self.timer.cancel()
        delay = max(0, self.adapter.deadline - self.adapter.clock())
        self.timer = asyncio.get_running_loop().call_later(delay, self._expired)

    async def input_event(self, data):
        event, call_id = validate_event(data)
        if self.closed:
            raise ValueError('Bridge is closed')
        if event == 'door-call':
            result = await self.ring(call_id)
            accepted = result['ring_started']
        elif event in ('floor-call', 'internal-call', 'other-tenant'):
            self.adapter.note('input_ignored', reason=event)
            accepted = False
        elif event == 'visitor-left':
            accepted = self.adapter.call_id == call_id and self.adapter.is_live()
            if accepted:
                self.stop('visitor_left', notify_station=False)
                async with self.lock:
                    await self.reader.calls.hangup()
            else:
                self.adapter.note('input_ignored', reason='stale_call')
        elif event == 'line-lost':
            self.adapter.disconnect()
            self.stop('line_lost', notify_station=False)
            async with self.lock:
                await self.reader.calls.hangup()
            accepted = True
        elif event == 'line-restored':
            # Recovery never resumes an old conversation or unlock window.
            self.stop('line_restored', notify_station=False)
            self.adapter.reconnect()
            async with self.lock:
                await self.reader.calls.hangup()
            accepted = True
        else:
            self.adapter.failure = 'answer' if event == 'fail-next-answer' else 'door_release'
            self.adapter.note('failure_armed', command=self.adapter.failure)
            accepted = True
        return {'accepted': accepted, **self.status()}

    def native_event(self, action):
        if action == 'answered' and self.adapter.is_live():
            self.answer()
        elif action in ('ended', 'transport_failed'):
            self.stop()
            if action == 'transport_failed':
                self._schedule_hangup()

    def stop(self, reason='hangup', notify_station=True):
        self.audio.set_active(False)
        self.adapter.end(reason, notify_station=notify_station)
        if self.timer:
            self.timer.cancel()
            self.timer = None
        if self.hub.relay_unlocked:
            if self.hub.relock_handle:
                self.hub.relock_handle.cancel()
            self.hub.relock()

    def _expired(self):
        self.stop('timeout', notify_station=False)
        self.reader.event('sks_simulated_window_expired')
        self._schedule_hangup()

    def _schedule_hangup(self):
        if self.cleanup_tasks or self.closed:
            return
        task = asyncio.create_task(self.reader.calls.hangup())
        self.cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_done)

    def _cleanup_done(self, task):
        self.cleanup_tasks.discard(task)
        if not task.cancelled() and task.exception():
            self.reader.event('sks_call_cleanup_failed')

    async def hangup(self):
        self.stop()
        async with self.lock:
            await self.reader.calls.hangup()
        return self.status()

    def status(self):
        return {'sks': self.adapter.status(), 'audio': self.audio.status()}

    async def close(self):
        self.closed = True
        await self.hangup()
        if self.cleanup_tasks:
            await asyncio.gather(*tuple(self.cleanup_tasks), return_exceptions=True)
        self.audio.close()
