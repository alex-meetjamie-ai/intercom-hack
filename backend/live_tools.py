"""Opt-in real SIP/audio/ElevenLabs checks for the three client tools (uses credit)."""
import asyncio
import argparse
import json
import re
import aiohttp
from pathlib import Path

from arrivals import RECORDS
from eleven import ElevenAgent
from test_jamie import SipClient, server, speech, until


async def main(selected=()):
    target = Path(__file__).parent / '.state/live-tools-test.json'
    report = json.loads(target.read_text()) if selected and target.exists() else []
    cases = [('Alex', 'My name is Alex. I work here and I am coming to the office.', None)] + [
        (r['id'], r['example'], r['id']) for r in RECORDS
    ] + [('unknown', 'My name is Bob Smith from Acme Widgets. I am here to sell printer supplies to your office. I do not have an appointment.', None)]
    if selected:
        unknown = set(selected) - {case[0] for case in cases}
        if unknown:
            raise ValueError('Unknown scenarios: ' + ', '.join(unknown))
        cases = [case for case in cases if case[0] in selected]
    for name, words, record_id in cases:
        print('Calling Jamie with synthetic speech: ' + name, flush=True)
        async with server(ElevenAgent) as (jamie, url):
            client = SipClient(url, jamie.token)
            employee_http = aiohttp.ClientSession()
            employee_ws = await employee_http.ws_connect(url + '/employee?token=' + jamie.token, origin=url)
            async with asyncio.timeout(10):
                await employee_ws.receive_json()
            try:
                await client.connect()
                await client.invite()
                await client.answer()
                await until(lambda: client.nonzero > 4000)
                await asyncio.sleep(5)
                client.source.push(speech(text=words))
                allowed = name != 'unknown'
                # WebSocket heartbeats can restart aiohttp's per-message timeout.
                # Bound the entire wait so an agent that never asks fails clearly.
                async with asyncio.timeout(55):
                    notification = await employee_ws.receive_json()
                request = next(r for r in notification['requests'] if r['status'] == 'pending')
                await asyncio.sleep(2)
                assert not jamie.door.open, 'Door opened without employee confirmation'
                assert jamie.elevator.floor == 5
                visitor = jamie.call.visitor
                before_decision = list(jamie.messages)
                spoken = ' '.join(m['text'].lower() for m in before_decision if m['speaker'] == 'Jamie')
                assert spoken.count('let me check quickly') == 1, spoken
                assert not re.search(r'\b(colleague|employee|approval|approve)\b', spoken), spoken
                await employee_ws.send_json({'type': 'decision', 'id': request['id'],
                                             'decision': 'allow' if allowed else 'deny'})

                if allowed:
                    await client.accept_hangup()
                    await until(lambda: jamie.call is None, timeout=2)
                    assert jamie.error is None
                    assert jamie.door.open, 'Hangup shortened the unlock pulse'
                    assert jamie.elevator.floor == 0
                    assert any(a['tool'] == 'open_door' and a['ok'] for a in jamie.actions)
                    assert any(a['tool'] == 'send_elevator' and a['ok'] for a in jamie.actions)
                    assert list(jamie.messages) == before_decision, 'Agent spoke after the door opened'
                    if record_id:
                        assert record_id in visitor.approved
                    await until(lambda: not jamie.door.open, timeout=6)
                    if name == 'email-dhl':
                        await until(lambda: jamie.elevator.floor == 5, timeout=6)
                else:
                    await until(lambda: any(a['tool'] == 'open_door' and not a['ok'] for a in jamie.actions), timeout=5)
                    await until(lambda: any("can't let you in" in m['text'].lower()
                                           for m in list(jamie.messages)[len(before_decision):]), timeout=15)
                    assert not any(a['tool'] == 'open_door' and a['ok'] for a in jamie.actions)
                    assert not jamie.door.open
                    assert jamie.elevator.floor == 5
                result = {'case': name, 'passed': True, 'actions': list(jamie.actions),
                          'transcript': list(jamie.messages), 'elevator': jamie.elevator.status(),
                          'received_audible_samples': client.nonzero}
                report = [r for r in report if r['case'] != name] + [result]
                print(json.dumps(result), flush=True)
                if jamie.call:
                    await client.hangup()
                    await until(lambda: jamie.call is None)
            except Exception:
                print(json.dumps({'failed_case': name, 'actions': list(jamie.actions), 'transcript': list(jamie.messages), 'error': jamie.error}), flush=True)
                raise
            finally:
                await client.close()
                await employee_ws.close()
                await employee_http.close()
                target.parent.mkdir(mode=0o700, exist_ok=True)
                target.write_text(json.dumps(report, indent=2) + '\n')
    print(f'Passed {len(cases)} selected live SIP/ElevenLabs cases; {len(report)} successful scenarios saved.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cases', nargs='*', help='Optional scenario ids to retry')
    asyncio.run(main(parser.parse_args().cases))
