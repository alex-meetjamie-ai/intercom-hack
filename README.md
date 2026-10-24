# Jamie intercom prototype

Open **http://localhost:8740**, press **Jamie**, allow the microphone, and speak.
Jamie asks your name and reason for visiting, checks mock emails/calendar entries,
and asks a Jamie employee to decide. **Every visitor needs employee approval,
including Alex.** Open **http://localhost:8740/admin** in a second tab and press
**Allow** or **Deny** on the live notification. Matches are supporting evidence;
an employee can also allow an unmatched visitor. Dates/times never block entry.

If the name is unclear or the first lookup has no match, Jamie asks for it once
more and checks again. A second mismatch can still be reviewed by an employee;
it never grants entry automatically. If the visitor insists on entry, declines
more questions or asks for a colleague, Jamie skips further clarification and
requests employee approval with the visitor's stated name or description. Neither
Alex's name nor a calendar/email match is required to request approval. An actual
employee denial or timeout still ends the call; insistence cannot override it.

Jamie receives context from the **last five completed calls within 30 minutes**
at this intercom, including recent dialogue, the employee decision and whether
the door actually opened. A returning visitor who identifies themselves can
continue without repeating the introduction or records lookup. If they missed
the elevator directions or need the door reopened, Jamie requests a **new**
employee confirmation, repeats the full directions and opens again on Allow.
It asks one brief clarification if the returning visitor is ambiguous and does
not assume every new caller is the previous person. Directions-only questions
can be answered without requesting an opening.

The office has **40 seconds** to respond. Jamie speaks a progress update at
the start, then every **6 ± 1 seconds** (randomly 5–7 seconds between updates)
while the request is pending. Timeout plays “Sorry, no one is available to open
the door.” and hangs up. Deny plays
“Sorry, I can't let you in.” and hangs up. On Allow, Jamie first says “{Name, if known} please go to the elevator and press
the button for floor five. The elevator is in the yard, my colleague will wait
for you upstairs.” Only after the full audio
finishes does the simulated door open for five seconds, the elevator go to 0,
and the call end. Hanging up during the instructions leaves the door closed.
The unlock timer continues after successful hangup.
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

**Presentation:** http://localhost:8740/presentation uses large text and our SKS
photos on the problem slide. One solution slide reuses the interactive SVG from
How it works, with a photo of the wall terminals. It progressively adds the PCB
and network, pans down to the Raspberry Pi, then reveals Jamie and agent tools.
Overview then shows everything together. The final Demo slide
replaces the PCB, Raspberry Pi and UniFi with one Emulated module on the Mac.
The deck has no navigation bar, chapter headings or caption strips; each agent
tool is a separate connected module. Protocol labels remain on the connections.
Arrow keys or Space advance; Left or Shift+Space go back. After Demo, Next/Space
opens the intercom page without starting a call. Detailed wiring notes remain on
How it works.

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
    │     timed spoken updates → waits up to 40 seconds for Allow / Deny
    │     Allow → spoken elevator instructions → unlock after audio finishes
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
Jamie uses the female Sarah voice; its voice ID is saved in that definition and
applies to both the conversation and the cached announcements.
DeepSeek Flash 4.1 is explicitly configured with high reasoning effort. Jamie
must explain that a colleague can confirm entry, never invent an Alex-only rule
or claim an appointment is mandatory.
The supplied key needs ElevenLabs Agents read/write permissions to provision the
agent. Calls read its configured voice and use the signed-URL endpoint. Text to
Speech permission generates the six fixed announcements on the first call;
later calls reuse PCM files under ignored `backend/.state/speech/`. Changing a
phrase or voice produces a new cache entry. Personal greetings are generated
on demand without saving named audio to disk; if generation fails, the complete
cached directions play without the optional name. `backend/announcements.py` defines
the exact phrases and timing; `backend/eleven.py` plays them over the same SIP
call. The model stays silent during this final phase, preventing duplicate speech.

`backend/call_history.py` holds bounded recent-call context in memory. It expires
after 30 minutes and is cleared on backend restart, with no conversation archive
written to disk. `backend/eleven.py` sends the snapshot as the `recent_calls`
[ElevenLabs dynamic variable](https://elevenlabs.io/docs/eleven-agents/customization/personalization/dynamic-variables)
at the start of each call. History is shared by this single intercom, not a
verified caller identity. Old approvals and lookup IDs cannot authorize a new call.

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
call. The ElevenLabs tool allows 60 seconds; backend approval expiry is 40 seconds,
leaving time to play the final instruction or apology. A missing response fails
closed. Local announcements and WebSocket ping handling continue while waiting;
visitor speech cannot replace the employee decision or interrupt these messages.

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
on both tools. That earlier version used one model-generated acknowledgement;
the timed-announcement flow below supersedes it.

Timed-wait and name-retry verification (2026-10-24): all 30 offline tests passed.
Five real SIP/ElevenLabs cases passed: Alex allowed, unknown visitor denied,
approval timeout, corrected name after a failed lookup, and unclear name followed
by clarification. Approval expired after 10 seconds, with updates at 0, 3 and 6
seconds and a spoken apology before hangup. Approved visitors heard the full
elevator instruction before the door opened. Offline tests also verified that
hanging up during that instruction, or missing instruction audio, leaves the
door closed. Both name-retry scenarios asked exactly once before employee review.

Longer-wait and colleague fallback verification (2026-10-24): all 30 offline tests
passed. Live SIP/ElevenLabs checks verified DHL admission and a full 40-second
expiry, with observed update intervals of 5.33, 5.51, 6.32, 5.31, 5.74 and 5.71
seconds. Both used Sarah's voice. A separate live regression with high reasoning
verified an unknown visitor saying they had no appointment and asking for a
colleague: Jamie immediately sent an employee request, said “Let me ask my
colleague if they can let you in,” and opened only after Allow and the elevator
instruction. The test SIP client now continuously reads signaling to answer
WebSocket keepalives during long waits, matching browser behavior.

Personalized directions verification (2026-10-24): 32 offline tests passed,
including a supplied name and fallback to the full generic directions if name
audio generation fails. A live Alex call played the complete personalized yard,
elevator and upstairs-colleague directions before unlocking and hanging up.

Returning-visitor verification (2026-10-24): 36 offline tests passed, covering
history expiry, size limits, distinguishing employee Allow from an actual
opening, and a new approval for the next call. Two consecutive live SIP/ElevenLabs
calls passed: Maya's interview arrival, then a callback after missing the elevator.
The callback skipped the lookup and repeated questions, requested a fresh Allow,
repeated the complete directions and reopened the simulated door before hangup.
Re-run with `backend/.venv/bin/python backend/live_returning.py` (uses credits).

For real voice scenarios (Alex, four mock arrivals, unknown visitor, unnamed
parcel courier, approval timeout, colleague escalation, corrected name and
unclear name), including hangup and the elevator return:

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
