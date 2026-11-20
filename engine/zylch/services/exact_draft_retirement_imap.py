"""Exact UID MOVE on the same fully inventoried mailbox connection."""

import re

from .exact_draft_delivery import EvidenceRefusal
from .exact_draft_publication_imap import ReviewMailbox


class RetirementMailbox(ReviewMailbox):
    def move(self, target, trash):
        if self.conn.select(target["folder"], readonly=False)[0] != "OK":
            raise EvidenceRefusal("drafts_folder_unavailable")
        if self.conn.untagged_responses.get("UIDVALIDITY") != [target["uidvalidity"].encode()]:
            raise EvidenceRefusal("uidvalidity_changed")
        status, data = self.conn.uid("MOVE", target["uid"], trash["folder"])
        if status != "OK":
            raise EvidenceRefusal("move_unconfirmed")
        result = {"acknowledged": True}
        candidates = list(data or []) + list(self.conn.untagged_responses.get("COPYUID", []))
        found = []
        for value in candidates:
            if isinstance(value, bytes):
                match = re.search(rb"(?:COPYUID )?(\d+) (\d+) (\d+)(?=\]|$)", value)
                if b"COPYUID" in value and match is None:
                    raise EvidenceRefusal("copyuid_ambiguous")
                if match:
                    found.append(tuple(part.decode() for part in match.groups()))
        if found:
            if len(set(found)) != 1 or found[0][1] != target["uid"]:
                raise EvidenceRefusal("copyuid_ambiguous")
            result["copyuid"] = {"uidvalidity": found[0][0], "uid": found[0][2]}
        return result
