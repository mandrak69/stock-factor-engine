from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
import gzip
import hashlib
import json
from pathlib import Path
import threading
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlsplit
import re


class EvidenceStore:
    def __init__(self, directory, user_agent):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent
        self.locks = {'sec': threading.Lock(), 'yahoo': threading.Lock()}
        self.last = {'sec': 0.0, 'yahoo': 0.0}

    def get(self, key, url, provider):
        host = {'sec': 'data.sec.gov', 'yahoo': 'query1.finance.yahoo.com'}[provider]
        target = urlsplit(url)
        if target.scheme != 'https' or target.hostname != host or target.username or target.password:
            raise ValueError('Evidence provider URL must match its configured HTTPS host')
        if not re.fullmatch(r'[A-Za-z0-9_.^\-]+', key):
            raise ValueError('Invalid evidence key')
        path = self.directory / (key + '.json.gz')
        metadata = self.directory / (key + '.meta.json')
        if path.exists() and metadata.exists():
            content = gzip.decompress(path.read_bytes())
            meta = json.loads(metadata.read_text(encoding='utf-8'))
            if hashlib.sha256(content).hexdigest() != meta['sha256'] or meta['url'] != url:
                raise ValueError('Cached evidence hash or URL mismatch: ' + key)
            return json.loads(content), meta
        for attempt in range(3):
            try:
                with self.locks[provider]:
                    interval = .55 if provider == 'sec' else .35
                    time.sleep(max(0, interval - (time.monotonic() - self.last[provider])))
                    self.last[provider] = time.monotonic()
                agent = self.user_agent if provider == 'sec' else 'stock-factor-engine/0.1 research'
                request = Request(url, headers={'User-Agent': agent, 'Accept': 'application/json'})
                with urlopen(request, timeout=40) as response:
                    content = response.read()
                payload = json.loads(content)
                meta = {'url': url, 'retrieved_at': datetime.now(UTC).isoformat(),
                        'sha256': hashlib.sha256(content).hexdigest(), 'file': str(path)}
                path.write_bytes(gzip.compress(content))
                metadata.write_text(json.dumps(meta, indent=2), encoding='utf-8')
                return payload, meta
            except HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
                time.sleep(2 ** attempt)
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)


def download_universe(store, members, *, include_sec=False):
    jobs = []
    for member in members:
        symbol = member['ticker'].replace('.', '-')
        jobs.append(('yahoo', 'chart_' + symbol,
                     'https://query1.finance.yahoo.com/v8/finance/chart/' + symbol +
                     '?range=2y&interval=1d&events=div%2Csplits&includeAdjustedClose=true'))
        if include_sec and member['sector'] not in ('Financials', 'Utilities'):
            cik = member['cik']
            jobs.extend([
                ('sec', 'submissions_' + cik, 'https://data.sec.gov/submissions/CIK' + cik + '.json'),
                ('sec', 'facts_' + cik, 'https://data.sec.gov/api/xbrl/companyfacts/CIK' + cik + '.json'),
            ])
    for symbol in ('SPY', 'RSP', 'HYG', 'LQD', '^VIX'):
        jobs.append(('yahoo', 'chart_' + symbol,
                     'https://query1.finance.yahoo.com/v8/finance/chart/' + symbol +
                     '?range=2y&interval=1d&events=div%2Csplits&includeAdjustedClose=true'))
    jobs = list(dict.fromkeys(jobs))
    errors = {}
    def run(job):
        provider, key, url = job
        return store.get(key, url, provider)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(run, job): job for job in jobs}
        for index, future in enumerate(as_completed(futures), 1):
            job = futures[future]
            try:
                future.result()
            except Exception as error:
                errors[job[1]] = type(error).__name__ + ': ' + str(error)
                print('ERROR', job[1], errors[job[1]], flush=True)
            if index % 50 == 0 or index == len(jobs):
                print(f'Downloaded/checked {index}/{len(jobs)}; errors={len(errors)}', flush=True)
    (store.directory.parent / 'download_errors.json').write_text(json.dumps(errors, indent=2), encoding='utf-8')
    return errors
