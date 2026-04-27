from __future__ import annotations

import unittest

from decide_me.projections import default_session_state
from decide_me.validate import StateValidationError, validate_session_state
from tests.helpers.legacy_term_policy import LEGACY_CLOSE_SUMMARY_TERMS


class NoLegacyCloseSummaryKeysTests(unittest.TestCase):
    def test_session_validation_rejects_legacy_close_summary_keys(self) -> None:
        session = default_session_state("S-001", "2026-04-23T12:00:00Z")
        legacy_key = next(term for term in LEGACY_CLOSE_SUMMARY_TERMS if term.endswith("action" + "_slices"))
        session["close_summary"][legacy_key] = []

        with self.assertRaisesRegex(StateValidationError, legacy_key):
            validate_session_state(session)


if __name__ == "__main__":
    unittest.main()
