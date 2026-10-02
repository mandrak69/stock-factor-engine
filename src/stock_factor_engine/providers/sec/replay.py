import hashlib
from datetime import datetime
from pathlib import Path

from .client import BASE_URL


class ReplayClient:
    """Replay a prior run's original bytes, verifying hashes and path containment."""

    def __init__(self, connection, data_dir: Path, run_id: str):
        self.root = Path(data_dir).resolve()
        self.documents = {}
        for row in connection.execute('SELECT * FROM raw_documents WHERE ingestion_run_id=?', (run_id,)):
            if row['source_url'] in self.documents:
                raise ValueError('Multiple responses for one URL in replay run')
            self.documents[row['source_url']] = row
        if not self.documents:
            raise ValueError('Replay run contains no raw documents')

    def fetch(self, path):
        document = self.documents.get(BASE_URL + path)
        if document is None:
            raise ValueError('Required URL missing from replay run')
        location = (self.root / document['relative_path']).resolve()
        if not location.is_relative_to(self.root):
            raise ValueError('Raw document path escapes data directory')
        content = location.read_bytes()
        if hashlib.sha256(content).hexdigest() != document['sha256']:
            raise ValueError('Raw document hash mismatch')
        return content, datetime.fromisoformat(document['retrieved_at'])
