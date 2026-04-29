from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


class SafetyApprovalSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "schemas" / "safety-approval.schema.json"
        self.validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))

    def test_accepts_approval_report(self) -> None:
        errors = list(self.validator.iter_errors(_valid_report()))

        self.assertEqual([], errors)

    def test_rejects_invalid_digest(self) -> None:
        payload = _valid_report()
        payload["approvals"][0]["gate_digest"] = "bad"

        errors = list(self.validator.iter_errors(payload))

        self.assertTrue(errors)


def _valid_report() -> dict:
    return {
        "schema_version": 1,
        "project_head": "H-test",
        "generated_at": "2026-04-28T00:00:00Z",
        "as_of": "2026-04-28T00:00:00Z",
        "object_id": "D-001",
        "active_gate_digest": "SG-123456789abc",
        "approvals": [
            {
                "artifact_id": "ART-approval-D-001-123456789abc",
                "status": "active",
                "target_object_id": "D-001",
                "gate_digest": "SG-123456789abc",
                "approval_threshold": "human_review",
                "approved_by": "user",
                "approved_at": "2026-04-28T00:00:00Z",
                "reason": "Reviewed.",
                "expires_at": None,
                "is_expired": False,
                "is_current": True,
                "addresses_link_ids": ["L-ART-approval-D-001-addresses-D-001"],
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
