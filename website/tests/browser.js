import { UserAgent, Inviter, SessionState, Web } from 'sip.js';

const result = document.querySelector('#result');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
document.querySelector('#run').onclick = async () => {
  let ua, session, ctx, oscillator;
  document.querySelector('#run').disabled = true;
  try {
    ctx = new AudioContext();
    await ctx.resume();
    const destination = ctx.createMediaStreamDestination();
    oscillator = ctx.createOscillator();
    oscillator.frequency.value = 440;
    const gain = ctx.createGain(); gain.gain.value = .1;
    oscillator.connect(gain).connect(destination);
    oscillator.start();
    const config = await fetch('/api/config').then(r => r.json());
    ua = new UserAgent({
      uri: UserAgent.makeURI('sip:visitor@localhost'), displayName: 'Visitor', logBuiltinEnabled: false,
      transportOptions: { server: `ws://${location.host}/sip?token=${encodeURIComponent(config.token)}` },
      sessionDescriptionHandlerFactory: Web.defaultSessionDescriptionHandlerFactory(async () => destination.stream),
      sessionDescriptionHandlerFactoryOptions: {
        constraints: { audio: true, video: false }, peerConnectionConfiguration: { iceServers: [] }, iceGatheringTimeout: 1500,
      },
    });
    await ua.start();
    session = new Inviter(ua, UserAgent.makeURI('sip:jamie@localhost'));
    result.textContent = 'Calling through SIP.js…';
    const established = new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('SIP call timed out')), 15000);
      session.stateChange.addListener(state => {
        if (state === SessionState.Established) { clearTimeout(timeout); resolve(); }
        if (state === SessionState.Terminated) { clearTimeout(timeout); reject(new Error('Call rejected')); }
      });
    });
    await session.invite();
    await established;
    const pc = session.sessionDescriptionHandler.peerConnection;
    const remote = new MediaStream(pc.getReceivers().map(r => r.track).filter(Boolean));
    const player = document.querySelector('#remote');
    player.srcObject = remote;
    await player.play();
    const analyser = ctx.createAnalyser(); analyser.fftSize = 1024;
    ctx.createMediaStreamSource(remote).connect(analyser);
    const silentOutput = ctx.createGain(); silentOutput.gain.value = 0;
    analyser.connect(silentOutput).connect(ctx.destination);
    let peak = 0, status;
    const data = new Float32Array(analyser.fftSize);
    for (let i = 0; i < 60; i++) {
      analyser.getFloatTimeDomainData(data);
      peak = Math.max(peak, ...data.map(Math.abs));
      status = await fetch('/api/status').then(r => r.json());
      if (peak > .01 && status.audio.sent_samples > 1000) break;
      await sleep(100);
    }
    if (!(peak > .01 && status.audio.sent_samples > 1000)) {
      const stats = await pc.getStats();
      throw new Error('Missing two-way media: ' + JSON.stringify({peak, audioContext:ctx.state,
        tracks:remote.getTracks().map(t => ({kind:t.kind, muted:t.muted, enabled:t.enabled, state:t.readyState})),
        inbound:[...stats.values()].filter(s => s.type === 'inbound-rtp'), status}));
    }
    await session.bye();
    let ended;
    for (let i = 0; i < 30; i++) {
      ended = await fetch('/api/status').then(r => r.json());
      if (ended.call === 'idle') break;
      await sleep(100);
    }
    if (ended.call !== 'idle' || ended.door !== 'closed') throw new Error('Call did not clean up');
    result.textContent = JSON.stringify({passed:true, sip:'INVITE → 200 → ACK → BYE → 200',
      media:'Browser ↔ backend WebRTC / DTLS-SRTP', receivedAudioPeak:peak,
      audio:ended.audio, finalCall:ended.call, finalDoor:ended.door}, null, 2);
  } catch (e) {
    result.textContent = 'FAIL: ' + e.message;
  } finally {
    if (session?.state === SessionState.Established) await session.bye();
    if (ua) await ua.stop();
    oscillator?.stop();
    await ctx?.close();
    document.querySelector('#remote').srcObject = null;
    document.querySelector('#run').disabled = false;
  }
};
