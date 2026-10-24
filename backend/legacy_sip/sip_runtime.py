"""PJSUA2 SIP/RTP endpoint for the explicitly selected loopback lab.

No microphone, speaker, registrar, office controller or physical lock is opened.
PJSIP handles SDP, codecs, RTP, jitter buffering and SIP transaction lifetimes.
The private INVITE header is a lab credential, not standard SIP Digest auth.
"""
import asyncio
import gc
import re
import secrets
import time

import pjsua2 as pj


class AudioPort(pj.AudioMediaPort):
    def __init__(self, rate, source=None, sink=None):
        super().__init__()
        self.source, self.sink = source, sink
        self.enabled = True
        self.errors = 0
        fmt = pj.MediaFormatAudio()
        fmt.init(pj.PJMEDIA_FORMAT_PCM, rate, 1, 20000, 16)
        self.createPort('intercom-lab-pcm', fmt)

    def onFrameRequested(self, frame):
        try:
            data = self.source() if self.enabled and self.source else bytes(frame.size)
            if len(data) != frame.size:
                raise ValueError('PCM source frame size mismatch')
            frame.type = pj.PJMEDIA_FRAME_TYPE_AUDIO
            frame.buf.assign_from_bytes(data)
        except Exception:
            self.errors += 1
            frame.type = pj.PJMEDIA_FRAME_TYPE_AUDIO
            frame.buf.assign_from_bytes(bytes(frame.size))

    def onFrameReceived(self, frame):
        if self.enabled and self.sink and frame.type == pj.PJMEDIA_FRAME_TYPE_AUDIO:
            try:
                data = bytearray(frame.buf.size())
                frame.buf.copy_to_bytearray(data)
                self.sink(bytes(data))
            except Exception:
                self.errors += 1


class SipCall(pj.Call):
    def __init__(self, runtime, call_id=pj.PJSUA_INVALID_ID, rate=16000, source=None, sink=None):
        super().__init__(runtime.account, call_id)
        self.runtime, self.rate = runtime, rate
        self.source, self.sink = source, sink
        self.port = self.media = None
        self.confirmed = asyncio.Event()
        self.ended = asyncio.Event()
        self.state = 'new'
        self.code = 0
        self.on_state = None
        self.failure = None
        self.disconnected_at = None
        self.native_disposed = False
        self.runtime.calls.append(self)  # Keep SWIG directors alive until shutdown.

    def onCallState(self, prm):
        info = self.getInfo()
        self.state, self.code = info.stateText.lower(), int(info.lastStatusCode)
        if info.state == pj.PJSIP_INV_STATE_CONFIRMED:
            self.confirmed.set()
        elif info.state == pj.PJSIP_INV_STATE_DISCONNECTED:
            if self.port:
                self.port.enabled = False
            self.ended.set()
            self.disconnected_at = time.monotonic()
        if self.on_state:
            self.on_state(self.state)
        if self.ended.is_set():
            self.runtime.loop.call_soon(self.dispose_native)

    def dispose_native(self):
        # PJSUA2 Call's destructor touches its endpoint even after disconnect.
        # Destroy it explicitly before that endpoint or its call slot is reused.
        # SWIG delete_Call disowns the pointer, preventing a second destruction.
        if not self.native_disposed:
            self.native_disposed = True
            pj.Call.__swig_destroy__(self)

    def onCallMediaState(self, prm):
        try:
            info = self.getInfo()
            for item in info.media:
                if item.type != pj.PJMEDIA_TYPE_AUDIO or item.status != pj.PJSUA_CALL_MEDIA_ACTIVE:
                    continue
                if self.port:
                    return
                self.media = self.getAudioMedia(item.index)
                self.port = AudioPort(self.rate, self.source, self.sink)
                if self.source:
                    self.port.startTransmit(self.media)
                if self.sink:
                    self.media.startTransmit(self.port)
                return
        except Exception as exc:
            self.failure = type(exc).__name__
            self.runtime.loop.call_soon(self.stop)

    def accept(self, code=200):
        prm = pj.CallOpParam(True)
        prm.statusCode = code
        prm.opt.audioCount, prm.opt.videoCount = 1, 0
        self.answer(prm)

    def stop(self, code=603):
        if self.ended.is_set() or self.native_disposed:
            return
        prm = pj.CallOpParam()
        prm.statusCode = code
        try:
            self.hangup(prm)
        except pj.Error:
            # A concurrent remote BYE may already have removed the native call.
            self.ended.set()


class Account(pj.Account):
    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime

    def onIncomingCall(self, prm):
        runtime = self.runtime
        call = SipCall(runtime, prm.callId)
        # Never accept anonymous audio from outside this machine. Do not log SIP
        # bodies/headers: they contain the per-run credential.
        keys = re.findall(r'^X-Intercom-Lab-Key:\s*([^\r\n]+)',
                          prm.rdata.wholeMsg, re.I | re.M)
        allowed = (prm.rdata.srcAddress.startswith('127.0.0.1:') and len(keys) == 1
                   and secrets.compare_digest(keys[0].strip(), runtime.token))
        if not allowed or not runtime.incoming:
            runtime.rejected += 1
            call.accept(403)
        elif any(c is not call and not c.ended.is_set() for c in runtime.calls):
            runtime.rejected += 1
            call.accept(486)
        else:
            runtime.incoming(call)


class SipRuntime:
    def __init__(self, token, port=0, incoming=None):
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', token):
            raise ValueError('A private lab token of 32–128 URL-safe characters is required')
        self.token, self.incoming = token, incoming
        self.calls, self.rejected = [], 0
        self.loop = asyncio.get_running_loop()
        self.endpoint = pj.Endpoint()
        self.endpoint.libCreate()
        cfg = pj.EpConfig()
        cfg.uaConfig.threadCnt = 0
        cfg.uaConfig.mainThreadOnly = True
        cfg.uaConfig.maxCalls = 8
        cfg.uaConfig.userAgent = 'Intercom-SIP-Lab/1'
        cfg.logConfig.level = cfg.logConfig.consoleLevel = 0
        cfg.logConfig.msgLogging = False
        cfg.medConfig.clockRate = cfg.medConfig.sndClockRate = 48000
        cfg.medConfig.audioFramePtime = 20
        cfg.medConfig.noVad = True
        cfg.medConfig.ecTailLen = 0
        self.endpoint.libInit(cfg)
        transport = pj.TransportConfig()
        transport.port = port
        transport.boundAddress = transport.publicAddress = '127.0.0.1'
        self.transport = self.endpoint.transportCreate(pj.PJSIP_TRANSPORT_UDP, transport)
        self.port = int(self.endpoint.transportGetInfo(self.transport).localAddress.rsplit(':', 1)[1])
        self.endpoint.libStart()
        self.endpoint.audDevManager().setNullDev()
        # A small, interoperable baseline. G.711 is decoded/resampled by PJSIP;
        # the ElevenLabs worker receives mono PCM, never RTP headers.
        for codec in self.endpoint.codecEnum2():
            self.endpoint.codecSetPriority(codec.codecId,
                255 if codec.codecId.startswith('PCMU/') else
                254 if codec.codecId.startswith('PCMA/') else 0)
        self.account = Account(self)
        account_cfg = pj.AccountConfig()
        account_cfg.idUri = f'sip:intercom@127.0.0.1:{self.port}'
        account_cfg.sipConfig.transportId = self.transport
        account_cfg.mediaConfig.transportConfig.boundAddress = '127.0.0.1'
        account_cfg.mediaConfig.transportConfig.publicAddress = '127.0.0.1'
        account_cfg.mediaConfig.transportConfig.port = 0
        account_cfg.mediaConfig.srtpUse = pj.PJMEDIA_SRTP_DISABLED
        self.account.create(account_cfg)
        self.pump_task = asyncio.create_task(self._pump())

    async def _pump(self):
        while True:
            self.endpoint.libHandleEvents(0)
            # Release conference ports outside the native disconnect callback.
            # A brief grace period lets the bridge finish its queued removal.
            for call in tuple(self.calls):
                if call.disconnected_at and time.monotonic() - call.disconnected_at > .5:
                    call.dispose_native()
                    call.port = call.media = None
                    call.source = call.sink = call.on_state = None
                    self.calls.remove(call)
            await asyncio.sleep(.005)

    def dial(self, target_port, source, sink=None, token=None):
        if type(target_port) is not int or not 1024 <= target_port <= 65535:
            raise ValueError('Expected a loopback SIP port above 1023')
        call = SipCall(self, rate=48000, source=source, sink=sink)
        prm = pj.CallOpParam(True)
        prm.opt.audioCount, prm.opt.videoCount = 1, 0
        header = pj.SipHeader()
        header.hName = 'X-Intercom-Lab-Key'
        header.hValue = token or self.token
        prm.txOption.headers.append(header)
        call.makeCall(f'sip:transcribe@127.0.0.1:{target_port}', prm)
        return call

    async def close(self):
        if self.endpoint is None:
            return
        for call in self.calls:
            call.stop()
        await asyncio.sleep(.2)
        for call in self.calls:
            if call.port:
                call.port.enabled = False
                try:
                    if call.media and call.source:
                        call.port.stopTransmit(call.media)
                    if call.media and call.sink:
                        call.media.stopTransmit(call.port)
                except pj.Error:
                    pass
        await asyncio.sleep(.1)
        for call in self.calls:
            call.dispose_native()
            call.port = call.media = None
            call.source = call.sink = call.on_state = None
        self.calls.clear()
        self.account.shutdown()
        self.account = None
        gc.collect()
        self.pump_task.cancel()
        await asyncio.gather(self.pump_task, return_exceptions=True)
        self.endpoint.libDestroy()
        self.endpoint = None
