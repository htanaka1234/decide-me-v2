from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


class PlanSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "schemas" / "plan.schema.json"
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(self.schema)

    def test_accepts_object_native_action_plan_shape(self) -> None:
        errors = list(self.validator.iter_errors(_valid_plan()))

        self.assertEqual([], errors)

    def test_rejects_legacy_top_level_evidence_reference_shape(self) -> None:
        payload = _valid_plan()
        payload["action_plan"]["evidence" + "_refs"] = ["docs/auth.md"]

        errors = list(self.validator.iter_errors(payload))

        self.assertTrue(errors)


def _valid_plan() -> dict:
    return {
        "generated_at": "2026-04-23T12:00:00Z",
        "source_session_ids": ["S-001"],
        "status": "action-plan",
        "conflicts": [],
        "action_plan": {
            "readiness": "ready",
            "goals": [],
            "workstreams": [],
            "actions": [],
            "implementation_ready_actions": [],
            "blockers": [],
            "risks": [],
            "evidence": [
                {
                    "id": "O-evidence-001",
                    "title": "docs/auth.md",
                    "summary": "Auth docs resolve the decision.",
                    "status": "active",
                    "source": "docs",
                    "ref": "docs/auth.md",
                    "metadata": {"source": "docs", "source_ref": "docs/auth.md"},
                }
            ],
            "source_object_ids": ["D-auth", "O-evidence-001"],
            "source_link_ids": ["L-O-evidence-001-supports-D-auth"],
        },
    }


if __name__ == "__main__":
    unittest.main()
