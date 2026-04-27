from __future__ import annotations

import unittest

from decide_me.projections import default_session_state
from decide_me.validate import StateValidationError, validate_session_state


class NoLegacyCloseSummaryKeysTests(unittest.TestCase):
    def test_session_validation_rejects_legacy_close_summary_keys(self) -> None:
        session = default_session_state("S-001", "2026-04-23T12:00:00Z")
        session["close_summary"]["candidate_action_slices"] = []

        with self.assertRaisesRegex(StateValidationError, "legacy fields"):
            validate_session_state(session)


if __name__ == "__main__":
    unittest.main()
