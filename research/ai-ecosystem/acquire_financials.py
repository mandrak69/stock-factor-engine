"""Run from repo root. Uses authorized SEC contact exclusively on SEC hosts."""
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from stock_factor_engine.current.sources import EvidenceStore
from stock_factor_engine.ecosystem.financials import ISSUERS


class SafeRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if target.scheme != 'https' or target.username or target.password:
            raise ValueError('Invalid evidence redirect')
        if urlsplit(req.full_url).hostname in {'www.sec.gov', 'data.sec.gov'} and target.hostname not in {'www.sec.gov', 'data.sec.gov'}:
            raise ValueError('SEC contact cannot leave SEC domains')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def main():
    registry = Path('research/ai-ecosystem')
    base = Path('data/current-2026-11-20/raw')
    extra = Path('data/ai-ecosystem-2026-11-20/financial-evidence')
    agent = None
    for line in Path('.env').read_text().splitlines():
        if line.startswith('SEC_USER_AGENT='):
            agent = line.partition('=')[2].strip().strip('\"').strip("'")
    if not agent:
        raise ValueError('Missing previously authorized SEC_USER_AGENT')
    store = EvidenceStore(extra, agent)
    errors = {}
    for entity, cik in ISSUERS.items():
        for kind, url in [('submissions', f'https://data.sec.gov/submissions/CIK{cik}.json'),
                          ('facts', f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json')]:
            key = kind + '_' + cik
            if (base / (key + '.json.gz')).exists():
                continue
            try:
                store.get(key, url, 'sec')
                print(entity, kind, 'saved/checked', flush=True)
            except Exception as error:
                errors[key] = type(error).__name__ + ': ' + str(error)
    sources = {s['id']: s for s in json.loads((registry / 'sources.json').read_text())}
    documents = []
    for row in json.loads((registry / 'reviewed-statements.json').read_text()):
        documents.append((Path('data/ai-ecosystem-2026-11-20/evidence') / row['relative_file'],
                          sources[row['source_id']]['url'], row['sha256']))
    for row in json.loads((registry / 'supplemental.json').read_text()):
        if row.get('curated_extract_file'):
            destination = Path('data/ai-ecosystem-2026-11-20/supplemental-evidence') / row['evidence_file']
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((registry / 'excerpts' / row['curated_extract_file']).read_bytes())
        documents.append((Path('data/ai-ecosystem-2026-11-20/supplemental-evidence') / row['evidence_file'],
                          row['url'], row['sha256']))
    opener = build_opener(SafeRedirects())
    for path, url, expected in dict.fromkeys(documents):
        try:
            target = urlsplit(url)
            if target.scheme != 'https' or target.username or target.password:
                raise ValueError('Invalid primary evidence URL')
            if path.exists():
                data = path.read_bytes()
            else:
                user_agent = agent if target.hostname in {'www.sec.gov', 'data.sec.gov'} else 'stock-factor-engine/0.1 research'
                with opener.open(Request(url, headers={'User-Agent': user_agent}), timeout=40) as response:
                    data = response.read()
                digest = hashlib.sha256(data).hexdigest()
                if digest != expected:
                    path = path.with_name(path.stem + '-unreviewed-' + digest[:12] + path.suffix)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                path.with_suffix('.meta.json').write_text(json.dumps({'url': url, 'sha256': digest,
                    'retrieved_at': datetime.now(UTC).isoformat()}, indent=2))
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('Capture changed; historical extraction requires re-review or archived original')
        except Exception as error:
            errors[str(path)] = type(error).__name__ + ': ' + str(error)
    (extra / 'download_errors.json').write_text(json.dumps(errors, indent=2))
    print(json.dumps({'error_count': len(errors), 'errors': errors}, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
