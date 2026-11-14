"""Release gate, identity and authority (#258): the rows that need neither the trusted job (#254) nor
the signed receipt (#255).

An approval added by the change: the checks that judge a change are read from its base, so a head
that approves its own draft check is judged by nothing. With the check approved in the base too, the
same head is cleared: the approval's origin is the only difference.
"""
from __future__ import annotations

from tests.release_gate.common import SPEC_FILE, GateCase, edit_json


class IdentityTest(GateCase):
    def test_an_approval_the_change_adds_to_its_own_checks_judges_nothing(self):
        base = self.copy("base-draft")
        edit_json(base / SPEC_FILE, lambda doc: doc.pop("approval"))   # in the base, the check is a draft
        head = self.copy("head-approves")                               # the change carries it approved
        code, status, err = self.verify(head, base=base)
        self.assertNotCleared(code, status, err)
        self.assertEqual((code, status["decision"]), (2, "needs-review"))
        self.assertIn("no checks ran", status["reasons"])
        # The same head against a base whose check is approved: cleared.
        code, status, err = self.verify(head, base=self.clean)
        self.assertEqual((code, status["decision"]), (0, "accept"), err)
