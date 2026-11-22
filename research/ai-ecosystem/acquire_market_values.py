"""Restore pinned public size-filter evidence; never silently refresh a dated value."""
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urlsplit
from datetime import UTC,datetime
import hashlib,json


def main():
    registry=Path('research/ai-ecosystem')
    folder=Path('data/ai-ecosystem-2026-11-20/market-cap-evidence')
    folder.mkdir(parents=True,exist_ok=True)
    references={}
    for row in json.loads((registry/'market-values.json').read_text(encoding='utf-8')):
        for ref in [row]+([row['fx']] if row.get('fx') else []):
            if ref.get('evidence_file'):
                references[ref['evidence_file']]=ref
    errors={}
    for name,ref in references.items():
        try:
            path=folder/name
            target=urlsplit(ref['source_url'])
            if path.name!=name or target.scheme!='https' or target.hostname not in {'stockanalysis.com','query1.finance.yahoo.com','openai.com'}:
                raise ValueError('Invalid evidence path or provider URL')
            if path.exists():
                raw=path.read_bytes()
            else:
                with urlopen(Request(ref['source_url'],headers={'User-Agent':'stock-factor-engine/0.1 research'}),timeout=30) as response:
                    raw=response.read()
                digest=hashlib.sha256(raw).hexdigest()
                if digest!=ref['sha256']:
                    path=path.with_name(path.stem+'-unreviewed-'+digest[:12]+path.suffix)
                path.write_bytes(raw)
                path.with_suffix('.meta.json').write_text(json.dumps({'url':ref['source_url'],'sha256':digest,'retrieved_at':datetime.now(UTC).isoformat()},indent=2))
            if hashlib.sha256(raw).hexdigest()!=ref['sha256']:
                raise ValueError('Source changed; restore original capture or review a new dated snapshot')
        except Exception as error:
            errors[name]=type(error).__name__+': '+str(error)
    (folder/'download-errors.json').write_text(json.dumps(errors,indent=2))
    print(json.dumps({'checked':len(references),'errors':errors},indent=2))
    return 1 if errors else 0


if __name__=='__main__':
    raise SystemExit(main())
