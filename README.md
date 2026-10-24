# Jamie intercom prototype

Open **http://localhost:8740**, press **Jamie**, allow the microphone, and speak.
Jamie asks your name. “My name is Alex” allows the agent to open the simulated
door; other names are refused. The door closes after five seconds or when the
call ends. Conversation text and the door state appear beside the call button.

**How it works:** http://localhost:8740/how-it-works shows an animated connection
diagram. Its default full-system view includes all eight photographed SKS terminals,
the retained indoor station, a proposed Doorman branch, Wi-Fi/LAN, Raspberry Pi,
UniFi Access and ElevenLabs. Select a terminal to trace its cable, or use “Read the
pins” to enlarge the drawing. The SKS-to-Doorman interface is explicitly unverified:
the broken connection is not an installation pinout. Hardware links, Pi migration
and controller-to-agent SIP routing are planned, not demonstrated by this diagram.
Switch to “Browser demo” for the working Mac flow. In either view, switch Alex/Bob,
pause or replay, or select any of the six steps. This is a browser-only illustration;
it never starts a call, contacts ElevenLabs or invokes the door tool.

The website and backend are in `website/` and `backend/`. Everything is configured
on this Mac, including a private ElevenLabs agent. To restart:

```sh
cd /Users/alex/work/hack
./run.sh
```

Keep that terminal running. Use headphones if the microphone picks up Jamie's
voice from the speakers. If autoplay is blocked, press “Enable Jamie’s audio.”
Chrome or Safari on this Mac can open the localhost URL. This version accepts
one call at a time, with a three-minute limit, and listens only on loopback.

## How the call works

```text
Website (SIP.js)
    │ SIP over WebSocket: INVITE / ACK / BYE
    │ WebRTC: encrypted two-way audio (DTLS-SRTP)
    ▼
Python backend (aiohttp + aiortc)
    │ 16 kHz mono PCM over an authenticated WebSocket
    ▼
Private ElevenLabs voice agent
    │ open_door(name) client tool → backend checks the transcript and name
    ▼
In-memory door → website open/closed label
```

SIP sets up the call; audio travels over WebRTC, not over the SIP WebSocket.
The backend connects to ElevenLabs, handles its audio and client-tool events,
and returns speech on the same WebRTC call. There is no Asterisk or FreeSWITCH
service to maintain for this prototype.

The browser never receives the ElevenLabs key or signed conversation URL.
`backend/.env` contains the key; `.state/agent.json` contains the agent ID.
Both are excluded from Git. The agent definition is in `backend/agent_config.json`.
The supplied key needs ElevenLabs Agents read/write permissions to provision the
agent; normal calls need access to its signed-URL endpoint.

## Scope

This is a **simulated door**, with no physical lock, SKS bus, Ring, or UDM connection.
“Alex” is a spoken self-identification rule, not identity verification.
The SIP endpoint supports the browser call flow, not arbitrary SIP phones,
registration, trunking, or a full PBX. Calls use the ElevenLabs cloud and account
credits. The app keeps its transcript in memory; ElevenLabs account retention
settings still apply to its conversations.

The previous emulator/SIP prototype is preserved in `backend/legacy_sip/`.
Its adopted-device state and recordings were not copied. The original workspace
remains intact. Connecting the new voice-agent flow to the adopted UniFi emulator
is a separate next step; this browser test does not claim that route is connected.

## Fresh setup

Requirements: Python **3.11+** (tested with 3.14), Node.js/npm.

```sh
python3.14 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
chmod 600 backend/.env
# Edit backend/.env privately to add your ElevenLabs key.
backend/.venv/bin/python backend/setup_agent.py
npm --prefix website ci
npm --prefix website run build
./run.sh
```

On this Mac, **do not overwrite the existing `.env`**; it is already configured.
`setup_agent.py` creates an agent only when no saved ID exists. Editing the local
JSON alone does not update the existing remote agent.

## Verification

Offline protocol, media, and door-policy tests:

```sh
backend/.venv/bin/python -m unittest discover -s backend -p 'test_jamie.py' -v
```

Actual ElevenLabs integration with synthetic “Alex” and “Bob” speech (macOS
`say`; consumes a small amount of account credit; never uses your microphone):

```sh
backend/.venv/bin/python backend/test_jamie.py --live
```

This creates real SIP/WebRTC calls to a temporary backend, checks the returned
audio and the agent's tool decision, and saves a local report in
`backend/.state/live-test.json`. Both visitors were tested successfully on
2026-10-24: Alex admitted, Bob denied, with nonzero audio in both directions.

Browser SIP.js integration test with generated tones and a fake local agent:

```sh
npm --prefix website run build:test
backend/.venv/bin/python backend/browser_check.py
# Open http://localhost:8741/browser-test and press Run browser call test.
```

The test server is separate from the normal app and sends nothing to ElevenLabs.
Stop it when finished. The production server does not expose those test routes.
The SIP.js browser check passed on 2026-10-24: INVITE/ACK/BYE completed, generated
audio reached the backend, returned audio was decoded by the browser, and the
session returned to idle with the door closed. All seven offline tests also pass.
