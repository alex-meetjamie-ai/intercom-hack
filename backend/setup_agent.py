"""Create Jamie once, or update its local definition with --update."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import aiohttp
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent

async def main(update=False):
    load_dotenv(ROOT / '.env')
    output = ROOT / '.state/agent.json'
    if output.exists() and not update:
        print('An agent is already configured in backend/.state/agent.json.')
        return
    key = os.getenv('ELEVENLABS_API_KEY')
    if not key:
        raise SystemExit('Add ELEVENLABS_API_KEY to backend/.env first.')
    config = json.loads((ROOT / 'agent_config.json').read_text())
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25), trust_env=False) as client:
        base = 'https://api.elevenlabs.io/v1/convai/agents'
        existing = json.loads(output.read_text())['agent_id'] if output.exists() else None
        url = f'{base}/{existing}' if existing else base + '/create'
        # Updating only agent settings preserves the remote voice, privacy and
        # other platform settings. Reuse the saved agent rather than duplicating it.
        payload = {'conversation_config': {'agent': config['conversation_config']['agent']}} if existing else config
        async with client.request('PATCH' if existing else 'POST', url,
                                  headers={'xi-api-key': key}, json=payload) as response:
            data = await response.json()
            if response.status != 200:
                detail = data.get('detail', {})
                message = detail.get('message', detail) if isinstance(detail, dict) else detail
                print('ElevenLabs agent setup failed:', response.status, str(message).replace(key, '[redacted]')[:1500])
                raise SystemExit(1)
        if existing:
            async with client.get(url, headers={'xi-api-key': key}) as response:
                if response.status != 200:
                    raise SystemExit('Agent updated, but reading it back failed; verify in ElevenLabs.')
                saved = (await response.json())['conversation_config']['agent']
                expected = config['conversation_config']['agent']
                if (saved['first_message'] != expected['first_message'] or
                        saved['prompt']['prompt'] != expected['prompt']['prompt'] or
                        {t['name'] for t in saved['prompt'].get('tools', [])} !=
                        {t['name'] for t in expected['prompt']['tools']}):
                    raise SystemExit('Agent update did not match the local prompt/tools.')
            open_tool = next(t for t in saved['prompt']['tools'] if t['name'] == 'open_door')
            if open_tool.get('response_timeout_secs') != 120 or not open_tool.get('expects_response'):
                raise SystemExit('Employee approval wait settings were not saved correctly.')
            if open_tool.get('pre_tool_speech') != 'off':
                raise SystemExit('Automatic approval-tool speech must be off to avoid duplicate acknowledgements.')
            lookup = next(t for t in saved['prompt']['tools'] if t['name'] == 'check_calendar_emails')
            if lookup.get('pre_tool_speech') != 'off':
                raise SystemExit('Silent lookup setting was not saved correctly.')
            print('Updated the existing private Jamie agent; verified one acknowledgement, silent tools and approval wait settings.')
            return
    output.parent.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump({'agent_id': data['agent_id']}, f)
    print('Created the private Jamie agent; saved its ID locally.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--update', action='store_true', help='Apply agent_config.json to the saved agent')
    asyncio.run(main(parser.parse_args().update))
