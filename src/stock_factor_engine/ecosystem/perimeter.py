"""Dated, evidence-backed parent/subsidiary folding for analytical accounts."""
import hashlib
from .model import instant


def accounting_perimeter(members, controls, evidence_dir, *, as_of, period_start, period_end):
    members = set(members)
    parents = {}
    for row in controls:
        if instant(row['available_at']) > instant(as_of):
            continue
        if not (row['period_start'] <= period_start <= period_end <= row['period_end']):
            continue
        parent, child = row['parent_id'], row['subsidiary_id']
        if parent not in members or child not in members or parent == child:
            raise ValueError('Invalid parent/subsidiary IDs')
        if row.get('reported_control') is not True:
            raise ValueError('Share ownership alone does not establish consolidation control')
        path = evidence_dir / row['evidence_file']
        if path.name != row['evidence_file'] or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('Control evidence path/hash mismatch')
        if child in parents and parents[child] != parent:
            raise ValueError('Conflicting controlling parents')
        parents[child] = parent
    canonical = {}
    for member in sorted(members):
        current, seen = member, set()
        while current in parents:
            if current in seen:
                raise ValueError('Control graph cycle')
            seen.add(current)
            current = parents[current]
        canonical[member] = current
    return {'members': sorted(set(canonical.values())), 'canonical': canonical,
            'note': 'Known controls folded; complete legal/control perimeter still requires reviewed attestation'}
