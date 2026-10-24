"""Opt-in two-call SIP/ElevenLabs memory check, using synthetic speech and credit."""
import asyncio
import json
from pathlib import Path

from announcements import entry_message
from eleven import ElevenAgent
from test_jamie import SipClient, server, speech, until


async def main():
    report = []
    async with server(ElevenAgent) as (jamie, url):
        words = [
            'My name is Maya Weber. I am here for my interview.',
            "Hi, it is Maya again. I just called. I couldn't find the elevator and the door closed. Can you open it again?",
        ]
        for index, utterance in enumerate(words):
            print('Starting ' + ('first visit' if index == 0 else 'returning visit'), flush=True)
            client = SipClient(url, jamie.token)
            try:
                await client.connect()
                await client.invite()
                await client.answer()
                visitor = jamie.call.visitor
                assert len(visitor.recent_calls) == index
                await until(lambda: client.nonzero > 4000)
                await asyncio.sleep(4)
                client.source.push(speech(text=utterance))
                await until(lambda: any(r['status'] == 'pending' for r in jamie.approvals.snapshot()), timeout=40)
                pending = next(r for r in jamie.approvals.snapshot() if r['status'] == 'pending')
                assert not jamie.door.open, 'Reused an old approval'
                if index:
                    assert not visitor.approved, 'Returning visitor repeated the records lookup'
                    assert not any(m['speaker'] == 'Jamie' and '?' in m['text']
                                   for m in list(jamie.messages)[1:]), 'Returning visitor was re-interviewed'
                    assert pending['id'] != report[0]['request_id']
                else:
                    assert 'calendar-interview' in visitor.approved
                await asyncio.sleep(1)
                jamie.approvals.decide(pending['id'], 'allow')
                expected = entry_message(pending.get('personal_name'))
                await until(lambda: any(m['text'] == expected for m in jamie.messages), timeout=12)
                assert not jamie.door.open, 'Opened before directions finished'
                await client.accept_hangup(timeout=18)
                await until(lambda: jamie.call is None)
                assert jamie.error is None, jamie.error
                assert visitor.admitted and jamie.door.open
                assert jamie.elevator.floor == 0
                assert client.nonzero > 4000
                report.append({'case': 'returning' if index else 'first', 'passed': True,
                               'request_id': pending['id'], 'transcript': list(jamie.messages),
                               'actions': list(jamie.actions), 'context_calls': len(visitor.recent_calls)})
                print(json.dumps({'case': report[-1]['case'], 'passed': True,
                                  'transcript': report[-1]['transcript']}), flush=True)
                await until(lambda: not jamie.door.open, timeout=6)
            except BaseException:
                print(json.dumps({'transcript': list(jamie.messages), 'actions': list(jamie.actions),
                                  'error': jamie.error}), flush=True)
                raise
            finally:
                await client.close()
    target = Path(__file__).parent / '.state/live-returning-test.json'
    target.parent.mkdir(mode=0o700, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + '\n')
    print('Passed two consecutive live SIP calls: fresh approval, repeated directions and second opening.', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
