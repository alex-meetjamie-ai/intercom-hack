"""Short, cached announcements in the configured Jamie voice."""
import hashlib
import json
import random
from itertools import cycle
from pathlib import Path

ROOT = Path(__file__).resolve().parent
def wait_schedule(timeout, interval=6, jitter=1):
    """Start immediately, then space announcements 6 ± 1 seconds apart."""
    yield 0, 'reaching'
    offset = 0
    for message in cycle(('trying', 'waiting')):
        offset += interval + random.uniform(-jitter, jitter)
        if offset >= timeout:
            return
        yield offset, message


TEXT = {
    'reaching': 'Let me ask my colleague if they can let you in.',
    'trying': "I'm still trying to reach someone for you.",
    'waiting': "I'm waiting for someone in the office to respond.",
    'entry': 'Please go to the elevator and press the button for floor five. The elevator is in the yard, my colleague will wait for you upstairs.',
    'timeout': 'Sorry, no one is available to open the door.',
    'denied': "Sorry, I can't let you in.",
}


def entry_message(personal_name=None):
    name = (personal_name or '').strip()
    return f"{name}, {TEXT['entry'][0].lower()}{TEXT['entry'][1:]}" if name else TEXT['entry']


async def load_announcements(http, key, agent_id, texts=None, cache_audio=True):
    headers = {'xi-api-key': key}
    async with http.get('https://api.elevenlabs.io/v1/convai/agents/' + agent_id,
                        headers=headers, allow_redirects=False) as response:
        if response.status != 200:
            raise RuntimeError(f'Could not read the Jamie voice (HTTP {response.status}).')
        tts = (await response.json())['conversation_config']['tts']
    voice = tts['voice_id']
    settings = {k: tts[k] for k in ('stability', 'similarity_boost', 'speed') if tts.get(k) is not None}
    cache = ROOT / '.state/speech'
    cache.mkdir(parents=True, exist_ok=True)
    clips = {}
    for name, text in (TEXT if texts is None else texts).items():
        payload = {'text': text, 'model_id': 'eleven_flash_v2', 'voice_settings': settings}
        digest = hashlib.sha256(json.dumps([voice, payload], sort_keys=True).encode()).hexdigest()
        path = cache / (digest + '.pcm')
        if cache_audio and path.exists():
            pcm = path.read_bytes()
        else:
            async with http.post('https://api.elevenlabs.io/v1/text-to-speech/' + voice,
                                 params={'output_format': 'pcm_16000'}, headers=headers,
                                 json=payload, allow_redirects=False) as response:
                if response.status != 200:
                    raise RuntimeError(f'Could not prepare Jamie announcements (HTTP {response.status}); the key needs Text to Speech permission.')
                pcm = await response.read()
            if not pcm or len(pcm) % 2 or len(pcm) > 32000 * 15:
                raise RuntimeError('Invalid announcement audio.')
            if cache_audio:
                path.write_bytes(pcm)
        clips[name] = pcm
    return clips
