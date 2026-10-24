"""Create the private Jamie voice agent once; never print the API key."""
import asyncio
import json
import os
from pathlib import Path
import aiohttp
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent

async def main():
    load_dotenv(ROOT / '.env')
    output = ROOT / '.state/agent.json'
    if output.exists():
        print('An agent is already configured in backend/.state/agent.json.')
        return
    key = os.getenv('ELEVENLABS_API_KEY')
    if not key:
        raise SystemExit('Add ELEVENLABS_API_KEY to backend/.env first.')
    config = json.loads((ROOT / 'agent_config.json').read_text())
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25), trust_env=False) as client:
        async with client.post('https://api.elevenlabs.io/v1/convai/agents/create',
                               headers={'xi-api-key': key}, json=config) as response:
            data = await response.json()
            if response.status != 200:
                detail = data.get('detail', {})
                message = detail.get('message', detail) if isinstance(detail, dict) else detail
                print('ElevenLabs agent setup failed:', response.status, str(message).replace(key, '[redacted]')[:1500])
                raise SystemExit(1)
    output.parent.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump({'agent_id': data['agent_id']}, f)
    print('Created the private Jamie agent; saved its ID locally.')

if __name__ == '__main__':
    asyncio.run(main())
