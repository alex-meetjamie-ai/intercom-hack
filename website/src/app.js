import { UserAgent, Inviter, SessionState } from 'sip.js';

const $ = (id) => document.getElementById(id);
let ua, session, starting = false, connectedAt, lastTranscript = '', localError = '';
const audio = $('remote-audio');
const emptyTranscript = $('transcript').innerHTML;

function error(message = '') {
  localError = message;
  $('error').textContent = message;
  $('error').hidden = !message;
}

function buttonState(active, pending = false) {
  $('call-button').classList.toggle('in-call', active);
  $('call-button').disabled = pending;
  $('call-name').textContent = active ? 'End call' : 'Jamie';
  $('call-action').textContent = active ? 'TAP TO HANG UP' : pending ? 'CONNECTING…' : 'PRESS TO CALL';
  $('avatar').classList.toggle('active', active);
  $('call-hint').textContent = active ? 'Microphone on' : 'Your microphone turns on when you call';
}

async function play() {
  try { await audio.play(); $('play-audio').hidden = true; }
  catch { $('play-audio').hidden = false; }
}
$('play-audio').addEventListener('click', play);

function attachMedia(current) {
  const pc = current.sessionDescriptionHandler?.peerConnection;
  if (!pc) return;
  audio.srcObject = new MediaStream(pc.getReceivers().map(r => r.track).filter(Boolean));
  play();
}

async function cleanup() {
  const old = ua;
  ua = undefined; session = undefined; connectedAt = undefined; starting = false;
  audio.pause(); audio.srcObject = null;
  $('play-audio').hidden = true;
  buttonState(false);
  if (old) { try { await old.stop(); } catch {} }
}

async function call() {
  if (starting) return;
  if (session) {
    if (session.state === SessionState.Established) await session.bye();
    else if (session.state === SessionState.Establishing) await session.cancel();
    await cleanup();
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    error('Please open this page at localhost in a browser with microphone support.'); return;
  }
  starting = true;
  error(); buttonState(false, true);
  $('agent-state').textContent = 'Calling Jamie…';
  try {
    const config = await fetch('/api/config').then(r => r.json());
    ua = new UserAgent({
      uri: UserAgent.makeURI('sip:visitor@localhost'), displayName: 'Visitor',
      transportOptions: { server: `ws://${location.host}/sip?token=${encodeURIComponent(config.token)}` },
      logBuiltinEnabled: false,
      sessionDescriptionHandlerFactoryOptions: {
        constraints: { audio: true, video: false },
        peerConnectionConfiguration: { iceServers: [] }, iceGatheringTimeout: 1500,
      },
      delegate: { onDisconnect: () => { if (session) { error('Call disconnected. Please try again.'); cleanup(); } } },
    });
    await ua.start();
    const current = session = new Inviter(ua, UserAgent.makeURI('sip:jamie@localhost'));
    current.stateChange.addListener((state) => {
      if (state === SessionState.Established) {
        starting = false; connectedAt = Date.now();
        buttonState(true); $('agent-state').textContent = 'You’re speaking with Jamie';
        attachMedia(current);
      } else if (state === SessionState.Terminated) {
        cleanup();
      }
    });
    await current.invite({ requestDelegate: { onReject: () => {
      fetch('/api/status').then(r => r.json()).then(s => error(s.error || 'Jamie could not answer. Please try again.'));
    } } });
    starting = false;
    if (session && session.state !== SessionState.Terminated) buttonState(true);
  } catch (err) {
    error(err.name === 'NotAllowedError' ? 'Allow microphone access, then press Jamie again.' : 'Could not start the call. Check microphone access and the backend.');
    await cleanup();
  }
}
$('call-button').addEventListener('click', () => call().catch(() => { error('The call stopped. Please try again.'); cleanup(); }));

async function refresh() {
  try {
    const response = await fetch('/api/status');
    if (!response.ok) throw new Error();
    const state = await response.json();
    $('connection-dot').classList.add('online');
    $('connection-text').textContent = state.agent_configured ? 'Jamie is online' : 'Agent setup needed';
    $('door-card').classList.toggle('open', state.door === 'open');
    $('door-state').textContent = state.door === 'open' ? 'Door open' : 'Door closed';
    $('door-badge').textContent = state.door.toUpperCase();
    $('door-description').textContent = state.door === 'open' ? 'Welcome in. The door will close automatically.' : 'Jamie will let you know when you can enter.';
    const transcript = JSON.stringify(state.transcript);
    if (transcript !== lastTranscript) {
      lastTranscript = transcript;
      $('transcript').replaceChildren(...state.transcript.map(item => {
        const div = document.createElement('div'); div.className = 'message ' + (item.speaker === 'You' ? 'you' : 'jamie');
        const name = document.createElement('div'); name.className = 'speaker-name'; name.textContent = item.speaker;
        const text = document.createElement('p'); text.textContent = item.text;
        div.append(name, text); return div;
      }));
      if (!state.transcript.length) $('transcript').innerHTML = emptyTranscript;
      $('transcript').scrollTop = $('transcript').scrollHeight;
    }
    $('conversation-label').textContent = state.call === 'connected' ? 'LIVE' : state.call === 'ringing' ? 'CONNECTING' : state.transcript.length ? 'CALL ENDED' : 'NOT STARTED';
    if (!session && !starting) $('agent-state').textContent = 'Ready when you are';
    if (state.error && !localError) error(state.error);
    if (!state.agent_configured && !localError) error('Jamie’s ElevenLabs agent needs setup. The backend is running.');
  } catch {
    $('connection-dot').classList.remove('online'); $('connection-text').textContent = 'Backend offline';
  }
  if (connectedAt) {
    const seconds = Math.floor((Date.now() - connectedAt) / 1000);
    $('timer').textContent = `· ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
  } else $('timer').textContent = '';
}
refresh(); setInterval(refresh, 500);
window.addEventListener('pagehide', () => { if (session?.state === SessionState.Established) session.bye(); });
