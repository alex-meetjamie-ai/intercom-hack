# Jamie intercom prototype

Open **http://localhost:8740**, press **Jamie**, allow the microphone, and speak.
Jamie asks your name and reason for visiting, checks mock emails/calendar entries,
and asks a Jamie employee to decide. **Every visitor needs employee approval,
including Alex.** Open **http://localhost:8740/admin** in a second tab and press
**Allow** or **Deny** on the live notification. Matches are supporting evidence;
an employee can also allow an unmatched visitor. Dates/times never block entry.

Jamie says “Let me check quickly.” once before the lookup/approval sequence, without mentioning employee
approval. Allow opens the simulated door for five seconds, dispatches the elevator
to 0 and immediately ends the SIP call, with no extra speech or farewell. The
unlock timer continues after hangup. Deny, a 90-second timeout, or hanging up
before approval keeps the door closed. Deny and timeout play one short refusal,
then the backend hangs up after the audio drains. A stalled refusal is capped at
12 seconds, so it cannot leave the call open. Automatic pre-tool speech is off
for both lookup and approval to avoid a second waiting announcement.
The website shows the conversation, tool actions and simulated door/elevator.
Try DHL delivery, pizza, Maya Weber’s interview, or Tom Schneider’s network visit.
All example records are fictional.

After admitting someone, the backend automatically calls the elevator to **0**
before ending the call; it will take them to our office on **5**. All mock office
arrivals have floor 5 as their destination. The elevator starts on **5** and travels there after
**10 uninterrupted seconds** on floor 0 only, and accepts floors **0, E, 1–5**.
**E and 0 are separate stops.** Floor E has no automatic return.
Repeating a floor-0 request does not restart the countdown; sending it to
another floor cancels it. The return timer continues after the call ends. Changes
between floors are instantaneous in this simulation. The call has already ended
after admission, so subsequent spoken floor requests are no longer accepted.

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
    │ check_calendar_emails(query) → local mock arrival records
    │ open_door(name, match_id?) → WebSocket notification to employee Admin
    │     waits for Allow / Deny → unlock only after Allow
    │ Backend sends elevator to 0 → SIP BYE (no further model turn)
    ▼
In-memory door + elevator → website status and action log
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

## Admin review

Open **http://localhost:8740/admin** (or use Admin in the navigation).
It shows the exact mock inbox and calendar records used by the running backend,
including message/event bodies, scheduled times and matching rules. Times are
informational only. No real email or calendar accounts are connected.

Keep Admin open in a second tab while calling Jamie. The review shows the visitor
transcript, the agent's lookup query, links to matching records, the actual tool
request/response, and whether the backend granted or blocked an unlock. A lookup
with no match is shown separately from a blocked unlock; it may lead to a follow-up
question. Every visitor still needs employee approval. The review includes the
approval request and employee decision as well as the resulting unlock.

The review retains up to 100 actions and the last 30 transcript messages in memory,
until the next call or server restart. Records are read-only; employee decisions
use the authenticated local `/employee` WebSocket. On connection/reconnection it
sends a snapshot, then pushes each change. Multiple tabs receive updates; the
first decision wins. Old requests and replayed tools cannot reopen the door.

This is a local employee-view demo, **not separate employee account authentication**:
anyone with access to this localhost app can use Admin. The WebSocket requires the
same-origin session nonce and local Host/Origin checks. No email, browser push
permission or third-party notification service is needed. Recent approval notices
(up to 20) are in memory until restart. Denial/expiry cannot be retried in the same
call. The ElevenLabs tool waits up to 120 seconds; backend expiry is 90 seconds,
so lack of a response always fails closed. Audio and ping handling stay active
while the tool waits.

## Scope

The **door and elevator are simulated**, with no physical lock, elevator, SKS bus,
Ring, or UDM connection. Email and calendar data come from
`backend/mock_arrivals.json`; no real inbox or calendar is accessed.
`check_calendar_emails` matches both the model's query and the visitor transcript.
The `open_door` tool requires an explicit employee Allow for the active call.
Spoken claims, identifying as Alex and matching records cannot bypass that gate.
Records and visitor names are context, not identity verification. All three tools are defined in `backend/agent_config.json`; handlers
are in `backend/door.py`, `backend/approvals.py`, `backend/arrivals.py` and `backend/elevator.py`.
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
`setup_agent.py` creates an agent only when no saved ID exists. After editing the
local definition, update the existing remote agent (keeps its ID and platform settings):

```sh
backend/.venv/bin/python backend/setup_agent.py --update
```

The script reads the remote configuration back to verify the prompt and tools.

## Verification

Offline protocol, media, and door-policy tests:

```sh
backend/.venv/bin/python -m unittest discover -s backend -p 'test_*.py' -v
```

Actual ElevenLabs integration with synthetic “Alex” and “Bob” speech (macOS
`say`; consumes a small amount of account credit; never uses your microphone):

```sh
backend/.venv/bin/python backend/test_jamie.py --live
```

This creates real SIP/WebRTC calls to a temporary backend, checks the returned
audio and the agent's tool decision, and saves a local report in
`backend/.state/live-tools-test.json`. The test acts as the employee through the
WebSocket, checks that the door stays closed while waiting, then allows Alex and
denies Bob. It does not change decisions in the normal app.

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
session returned to idle with the door closed.

The expanded offline suite covers arrival matching, early/late arrivals, rejected
lookups, call-scoped approval, tool replay, all elevator floors, cancellation and
automatic return, plus ElevenLabs client-tool message/result correlation.

Employee approval verification (2026-10-24): all 24 offline tests passed, including
WebSocket broadcasts/reconnects, first-decision-wins, denied/expired/cancelled
requests and continued voice-agent ping handling while approval is pending.
Browser checks at desktop and mobile sizes verified Allow opens the simulated
door and dispatches the lift to 0, while Deny keeps both unchanged, including for
Alex. The live app has no automatic employee decisions; test approvals are sent
only by the isolated test clients.
Earlier employee-gate verification: three real SIP/ElevenLabs cases passed: Alex
allowed, DHL allowed, and an unknown sales visitor denied. Each stayed closed
before the WebSocket decision. Elevator dispatch, spoken boarding directions and
the return to floor 5 were verified after approval. Other saved live-test cases
in the report predate this policy and have not been rerun with the employee gate.

Immediate-hangup verification (2026-10-24): all 24 offline tests passed, including
server-initiated SIP BYE, no call error on success, and preserving the door pulse
and elevator timer after disconnect. Live Alex and DHL calls verified employee
approval, immediate BYE with no subsequent agent speech, and elevator dispatch.
A live denied visitor heard a short refusal and the door stayed closed. The final
silent-lookup setting was retested with DHL and the denied visitor; both used
“Let me check quickly” once and did not mention employee approval.

Refusal/duplicate-speech regression (2026-10-24): 27 offline tests passed,
including denied and expired requests playing audio before SIP BYE and a missing
audio response still ending the call. Live tests passed for Alex allowed, an
unknown visitor denied, an unnamed parcel courier denied, and approval expiry.
Each used one waiting phrase. Denied/expired calls played a short refusal and
ended with the door closed and elevator on 5. Forced pre-tool speech is now off
on both tools; the prompt provides one acknowledgement for the whole sequence.

For real voice scenarios (Alex, four mock arrivals, unknown visitor, unnamed
parcel courier and approval timeout), including hangup and the elevator return:

```sh
backend/.venv/bin/python backend/live_tools.py
```

This uses synthetic speech, temporary local SIP servers and ElevenLabs credits.
Its report stays in ignored `backend/.state/live-tools-test.json`.

Earlier verification, before employee confirmation was added: all 15 offline tests passed. Six live SIP/ElevenLabs
scenarios passed: Alex, DHL, pizza, early interview, late technician and an
unexpected sales visitor. The first five were admitted; the sales visitor was
refused after a lookup. Floor 3 and the ten-second return to 5 were verified.
The website was checked at desktop and mobile widths.

Earlier floor correction verified: 0 and E are separate stops. All 16 offline tests pass,
including staying on E and cancelling the floor-0 timer when moving to E. A live
DHL voice call verified automatic dispatch to 0 without a visitor request, spoken
boarding directions to the fifth-floor office, and the ten-second trip to 5.
