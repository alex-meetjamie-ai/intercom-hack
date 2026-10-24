# Previous emulator and SIP transcription prototype

Copied from:
`/Users/alex/Documents/Codex/2026-09-30/outputs-network-handoff-2026-09-30/outputs/unifi-access-poc`

This snapshot preserves the earlier UniFi reader/hub emulator, SKS simulation,
PJSUA2 SIP receiver, and ElevenLabs transcription work. See `SIP-TRANSCRIPTION.md`
for its original workflow. It has separate dependencies and is not imported by
the new browser backend.

Private adopted-device state, recordings, credentials and virtual environments
were deliberately left in the original workspace. Do not start this copy as a
second adopted device with a duplicate identity. The active browser prototype is
`../app.py`; its door is only an in-memory simulation.
