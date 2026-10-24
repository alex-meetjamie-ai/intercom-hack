"""In-memory door only. There is no physical unlock implementation."""
import asyncio
import re


class Door:
    def __init__(self, seconds=5):
        self.seconds = seconds
        self.open = False
        self.timer = None

    def unlock(self):
        self.close()
        self.open = True
        self.timer = asyncio.get_running_loop().call_later(self.seconds, self.close)

    def close(self):
        self.open = False
        if self.timer:
            self.timer.cancel()
            self.timer = None


class Visitor:
    def __init__(self, door):
        self.door = door
        self.name = None
        self.active = True
        self.results = {}

    def hear(self, text):
        # A second, conservative check on ASR text, independent of the LLM's
        # tool arguments. This is self-identification, not identity verification.
        text = text.casefold().replace('’', "'").strip()
        if re.search(r"\b(?:not|isn't|is not)\s+alex\b|\balex's\b", text):
            self.name = None
            return
        if re.fullmatch(r"alex[.!?, ]*", text):
            self.name = 'alex'
            return
        match = re.search(r"\b(?:my name is|i am|i'm|this is|it's)\s+([a-z]+)\b", text)
        if match:
            self.name = match.group(1)

    def tool(self, call_id, name, parameters):
        if call_id in self.results:
            return self.results[call_id]
        allowed = (self.active and name == 'open_door' and isinstance(parameters, dict)
                   and set(parameters) == {'name'} and isinstance(parameters['name'], str)
                   and parameters['name'].strip().casefold() == 'alex' and self.name == 'alex')
        if allowed:
            self.door.unlock()
            result = {'is_error': False, 'result': 'The simulated door is open. It closes automatically in five seconds.'}
        else:
            result = {'is_error': True, 'result': 'Door remains closed. The current visitor must explicitly identify themself as Alex.'}
        self.results[call_id] = result
        return result

    def close(self):
        self.active = False
        self.door.close()
