"""Explicit SIP alternative to NativeCalls for the local SKS/reader emulator."""
import asyncio


class SipCalls:
    pc = None

    def __init__(self, reader, runtime, target_port):
        self.reader, self.runtime, self.target_port = reader, runtime, target_port
        self.current = None
        self.state = 'idle'
        self.rings = self.hangups = 0
        self.last_code = 0

    async def ring(self):
        if self.current and not self.current.ended.is_set():
            raise ValueError('SIP call already active')
        audio = self.reader.ems.audio
        self.state = 'calling'
        self.rings += 1
        self.current = self.runtime.dial(self.target_port, audio.read_pcm)
        self.current.on_state = self._state_changed
        return self.status()

    def _state_changed(self, state):
        self.state = state
        if state == 'confirmed':
            self.reader.call_lifecycle('answered')
        elif state == 'disconnected':
            self.last_code = self.current.code
            self.reader.call_lifecycle('ended')
            self.state = 'idle'

    async def hangup(self):
        self.hangups += 1
        if self.current and not self.current.ended.is_set():
            self.current.stop()
            try:
                await asyncio.wait_for(self.current.ended.wait(), 3)
            except asyncio.TimeoutError:
                self.reader.call_lifecycle('transport_failed')
        self.state = 'idle'

    async def close(self):
        await self.hangup()
        await self.runtime.close()

    def status(self):
        return {'state': self.state, 'upstream': 'real_loopback_sip_rtp',
                'ring_requests': self.rings, 'hangup_requests': self.hangups,
                'last_sip_code': self.last_code,
                'media_failure': self.current.failure if self.current else None,
                'audio_callback_errors': self.current.port.errors
                    if self.current and self.current.port else 0}
