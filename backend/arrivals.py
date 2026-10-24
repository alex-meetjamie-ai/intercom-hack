"""Small local email/calendar fixtures. No clock or real account connection."""
import json
from pathlib import Path
import re

RECORDS = json.loads((Path(__file__).parent / 'mock_arrivals.json').read_text())


def normalize(text):
    return ' '.join(re.findall(r'\w+', text.casefold()))


def matches(record, text):
    text = ' ' + normalize(text) + ' '
    return all(any(' ' + normalize(term) + ' ' in text for term in group)
               for group in record['match_groups'])


def public_record(record):
    return {key: value for key, value in record.items() if key != 'match_groups'}


def lookup(query, heard):
    # The agent cannot grant access by inventing a matching query: the visitor's
    # ASR transcript must also match. This is still a demo, not identity proof.
    return [public_record(record) for record in RECORDS
            if matches(record, query) and matches(record, heard)]
