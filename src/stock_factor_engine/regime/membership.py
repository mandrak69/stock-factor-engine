"""Explicit import contract for independently verified, exact-date membership.

This does not download or independently certify S&P membership. The caller owns
the source's completeness/provenance; a current-list JSON must never be relabeled
as historical membership. IDs refer to securities already in the local database.
"""
from datetime import date
import json
from pathlib import Path

from .inputs import Membership


class JsonMembershipProvider:
    def __init__(self, path):
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(payload, dict):
            raise ValueError('Membership JSON must be an object')
        members = payload.get('security_ids')
        source = payload.get('source')
        if (not isinstance(members, list) or not members
                or any(not isinstance(item, str) or not item.strip() for item in members)
                or len(set(members)) != len(members)):
            raise ValueError('Membership requires nonempty unique security_ids')
        if not isinstance(source, str) or not source.strip():
            raise ValueError('Membership source provenance is required')
        if payload.get('complete') is not True:
            raise ValueError('Membership must be independently verified complete')
        self.membership = Membership(date.fromisoformat(payload['session']), frozenset(members), source, True)

    def members_on(self, session):
        return self.membership if self.membership.session == session else None
