from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = 'https://data.sec.gov'


def normalize_cik(value: str) -> str:
    if not re.fullmatch(r'[0-9]{1,10}', value) or int(value) == 0:
        raise ValueError('CIK must contain 1 to 10 digits and be positive')
    return value.zfill(10)


def decode_json(payload: bytes) -> dict:
    def reject_constant(value):
        raise ValueError(f'Invalid JSON number: {value}')
    result = json.loads(payload, parse_float=Decimal, parse_constant=reject_constant)
    if not isinstance(result, dict):
        raise ValueError('SEC response must be a JSON object')
    return result


class SecClient:
    """Single-threaded client: at most two requests per second, bounded retries."""

    def __init__(self, user_agent: str):
        if not re.search(r'[^\s@]+@[^\s@]+\.[^\s@]+', user_agent) or '\n' in user_agent or '\r' in user_agent:
            raise ValueError('SEC User-Agent must identify the application and contact email')
        self.user_agent = user_agent
        self._last_request = 0.0

    def fetch(self, path: str) -> tuple[bytes, datetime]:
        if not re.fullmatch(r'/(submissions/[A-Za-z0-9-]+\.json|api/xbrl/companyfacts/CIK[0-9]{10}\.json)', path):
            raise ValueError('Unsupported SEC API path')
        for attempt in range(3):
            time.sleep(max(0, 0.5 - (time.monotonic() - self._last_request)))
            self._last_request = time.monotonic()
            request = Request(BASE_URL + path, headers={
                'User-Agent': self.user_agent, 'Accept': 'application/json',
                'Accept-Encoding': 'identity',
            })
            try:
                with urlopen(request, timeout=30) as response:
                    payload = response.read()
                return payload, datetime.now(UTC)
            except HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
                retry_after = error.headers.get('Retry-After', '')
                delay = min(30, max(2 ** attempt, int(retry_after))) if retry_after.isdigit() else 2 ** attempt
                time.sleep(delay)
            except (URLError, TimeoutError):
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError('Unreachable retry state')
