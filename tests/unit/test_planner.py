from __future__ import annotations

import unittest

from decide_me.planner import detect_conflicts


class PlannerTests(unittest.TestCase):
    def test_detects_accepted_answer_conflict(self) -> None:
        session_a = {
            "session": {"id": "S-001"},
            "close_summary": {
                "accepted_decisions": [
                    {
                        "id": "D-001",
                        "title": "Auth mode",
                        "accepted_answer": "Use magic links.",
                    }
                ],
                "candidate_workstreams": [],
                "candidate_action_slices": [],
            },
        }
        session_b = {
            "session": {"id": "S-002"},
            "close_summary": {
                "accepted_decisions": [
                    {
                        "id": "D-001",
                        "title": "Auth mode",
                        "accepted_answer": "Use passwords.",
                    }
                ],
                "candidate_workstreams": [],
                "candidate_action_slices": [],
            },
        }

        conflicts = detect_conflicts([session_a, session_b])
        self.assertEqual(1, len(conflicts))
        self.assertEqual("accepted-answer-mismatch", conflicts[0]["kind"])


if __name__ == "__main__":
    unittest.main()
