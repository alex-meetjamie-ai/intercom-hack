"""Opt-in real SIP/audio/ElevenLabs checks for the three client tools (uses credit)."""
import asyncio
import argparse
import json
import aiohttp
from pathlib import Path
from datetime import datetime

from arrivals import RECORDS
from announcements import TEXT, entry_message
from eleven import ElevenAgent
from test_jamie import SipClient, server, speech, until


class ObservedEleven(ElevenAgent):
    async def announce(self, name):
        if not hasattr(self, 'announcement_times'):
            self.announcement_times = []
        self.announcement_times.append((name, asyncio.get_running_loop().time()))
        await super().announce(name)


async def main(selected=()):
    target = Path(__file__).parent / '.state/live-tools-test.json'
    report = json.loads(target.read_text()) if selected and target.exists() else []
    cases = [('Alex', 'My name is Alex. I work here and I am coming to the office.', None)] + [
        (r['id'], r['example'], r['id']) for r in RECORDS
    ] + [('unknown', 'My name is Bob Smith from Acme Widgets. I am here to sell printer supplies to your office. I do not have an appointment.', None),
         ('unnamed-parcel', "I don't have a name. I just brought the parcel. What the fuck?", None),
         ('expired', 'My name is Alex. I work here and I am coming to the office.', None),
         ('insists', "My name is Jordan Smith. I do not have an appointment. Why can't you let me in? Please ask someone in the office to let me in.", None),
         ('name-corrected', 'My name is Maria Wilson. I am here for an interview.', 'calendar-interview'),
         ('unclear-name', 'I am here for an interview. My name is, uh... sorry.', 'calendar-interview')]
    repeats = {
        'unknown': 'Bob Smith, from Acme Widgets, here to sell printer supplies. I have no appointment.',
        'unnamed-parcel': "I already told you, it's a parcel delivery. I don't want to give my name.",
        'name-corrected': 'My name is Maya Weber. I am here for my interview.',
        'unclear-name': 'My name is Maya Weber. I am here for my interview.',
    }
    if selected:
        unknown = set(selected) - {case[0] for case in cases}
        if unknown:
            raise ValueError('Unknown scenarios: ' + ', '.join(unknown))
        cases = [case for case in cases if case[0] in selected]
    for name, words, record_id in cases:
        print('Calling Jamie with synthetic speech: ' + name, flush=True)
        async with server(ObservedEleven) as (jamie, url):
            client = SipClient(url, jamie.token)
            employee_http = aiohttp.ClientSession()
            employee_reader = None
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
                allowed = name not in ('unknown', 'unnamed-parcel', 'expired')
                if name in repeats:
                    await until(lambda: any(m['speaker'] == 'Jamie' and 'name' in m['text'].lower()
                                            and '?' in m['text'] for m in jamie.messages), timeout=25)
                    assert not jamie.approvals.snapshot(), 'Contacted the office before the one name retry'
                    await asyncio.sleep(3)
                    client.source.push(speech(text=repeats[name]))
                # WebSocket heartbeats can restart aiohttp's per-message timeout.
                # Bound the entire wait so an agent that never asks fails clearly.
                async with asyncio.timeout(55):
                    notification = await employee_ws.receive_json()
                request = next(r for r in notification['requests'] if r['status'] == 'pending')

                async def drain_employee_messages():
                    async for _ in employee_ws:
                        pass

                employee_reader = asyncio.create_task(drain_employee_messages())
                await asyncio.sleep(7.5)
                assert not jamie.door.open, 'Door opened without employee confirmation'
                assert jamie.elevator.floor == 5
                visitor = jamie.call.visitor
                agent = jamie.call.agent
                before_decision = list(jamie.messages)
                spoken = ' '.join(m['text'].lower() for m in before_decision if m['speaker'] == 'Jamie')
                assert spoken.count(TEXT['reaching'].lower()) == 1, spoken
                assert spoken.count(TEXT['trying'].lower()) == 1, spoken
                assert 'let me check quickly' not in spoken, spoken
                if name == 'insists':
                    assert not any(phrase in spoken for phrase in
                                   ('only alex', 'only let alex', 'only allow alex', 'only one person',
                                    'appointment is required', 'cannot let you in', "can't let you in")), spoken
                    assert not any(m['speaker'] == 'Jamie' and '?' in m['text']
                                   for m in before_decision[2:]), 'Insistence should reach a colleague without more questions'
                if name in repeats:
                    questions = [m for m in before_decision if m['speaker'] == 'Jamie'
                                 and 'name' in m['text'].lower() and '?' in m['text']]
                    assert len(questions) == 1, questions
                audible_before = client.nonzero
                if name != 'expired':
                    await employee_ws.send_json({'type': 'decision', 'id': request['id'],
                                                 'decision': 'allow' if allowed else 'deny'})

                if allowed:
                    if name in ('Alex', 'email-dhl'):
                        assert request.get('personal_name'), 'Agent omitted the available personal name'
                    expected_entry = entry_message(request.get('personal_name'))
                    await until(lambda: any(m['text'] == expected_entry for m in jamie.messages), timeout=12)
                    assert not jamie.door.open, 'Door opened before elevator instructions'
                    await asyncio.sleep(1)
                    assert not jamie.door.open, 'Door opened while elevator instructions were playing'
                    await client.accept_hangup(timeout=18)
                    await until(lambda: jamie.call is None, timeout=2)
                    assert jamie.error is None
                    assert jamie.door.open, 'Hangup shortened the unlock pulse'
                    assert jamie.elevator.floor == 0
                    assert any(a['tool'] == 'open_door' and a['ok'] for a in jamie.actions)
                    assert any(a['tool'] == 'send_elevator' and a['ok'] for a in jamie.actions)
                    assert [m['text'] for m in jamie.messages].count(expected_entry) == 1
                    assert client.nonzero > audible_before + 4000, 'Entry instructions were not audible'
                    if record_id:
                        assert record_id in visitor.approved
                    await until(lambda: not jamie.door.open, timeout=6)
                    if name == 'email-dhl':
                        await until(lambda: jamie.elevator.floor == 5, timeout=6)
                else:
                    await until(lambda: any(a['tool'] == 'open_door' and not a['ok'] for a in jamie.actions), timeout=45)
                    refusal = TEXT['timeout' if name == 'expired' else 'denied'].lower()
                    await until(lambda: any(refusal in m['text'].lower()
                                           for m in list(jamie.messages)[len(before_decision):]), timeout=15)
                    await client.accept_hangup(timeout=15)
                    await until(lambda: jamie.call is None, timeout=2)
                    assert jamie.error is None
                    assert client.nonzero > audible_before + 4000, 'Refusal was not audible before BYE'
                    assert not any(a['tool'] == 'open_door' and a['ok'] for a in jamie.actions)
                    assert not jamie.door.open
                    assert jamie.elevator.floor == 5
                    if name == 'expired':
                        final = jamie.approvals.snapshot()[0]
                        elapsed = (datetime.fromisoformat(final['decided_at']) - datetime.fromisoformat(final['created_at'])).total_seconds()
                        assert 39.9 <= elapsed <= 40.5, elapsed
                        updates = [t for message, t in agent.announcement_times
                                   if message in ('reaching', 'trying', 'waiting')]
                        assert len(updates) >= 6, updates
                        gaps = [b - a for a, b in zip(updates, updates[1:])]
                        assert all(4.9 <= gap <= 7.2 for gap in gaps), gaps
                        print('Observed waiting intervals: ' + ', '.join(f'{gap:.2f}s' for gap in gaps), flush=True)
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
                if employee_reader:
                    employee_reader.cancel()
                    await asyncio.gather(employee_reader, return_exceptions=True)
                await employee_http.close()
                target.parent.mkdir(mode=0o700, exist_ok=True)
                target.write_text(json.dumps(report, indent=2) + '\n')
    print(f'Passed {len(cases)} selected live SIP/ElevenLabs cases; {len(report)} successful scenarios saved.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cases', nargs='*', help='Optional scenario ids to retry')
    asyncio.run(main(parser.parse_args().cases))
