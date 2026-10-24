# Intercom client

Shared browser client for the existing backend on port 8740. Three.js imports it as `@intercom/client` through a local package dependency.

```js
import {createIntercomClient} from '@intercom/client';
const client = createIntercomClient({
  audio: document.querySelector('audio'),
  onStatus: state => console.log(state.door, state.transcript),
  onState: state => console.log(state),
  onError: error => console.error(error),
  onAudioBlocked: blocked => { /* show an Enable audio button */ },
});
// Run from a user click; the browser requests microphone access.
await client.ring();
await client.disconnect();
```

`ring()` / `connect()` starts SIP over WebSocket with WebRTC microphone/audio. `getStatus()` reads the backend; status also polls once per second. `playAudio()` retries playback when browser autoplay blocks it. `destroy()` ends the call and polling.

Backend surface used:
- `GET /api/config`: local connection token.
- `GET /api/status`: call, door, transcript, agent configuration and audio counters.
- `/sip?token=...`: SIP WebSocket; INVITE/ACK starts the call and BYE ends it.

`decide(false)` ends the call. `decide(true)` confirms that the backend has already opened its simulated door; otherwise it throws. The existing backend has no manual approval endpoint. Jamie grants entry through its voice-agent flow. The client does not fabricate an unlock API or send synthetic speech.

Vite proxies `/api` and `/sip` to the local backend. The backend must have its own ElevenLabs configuration for a live conversation; no keys are placed in the frontend.
