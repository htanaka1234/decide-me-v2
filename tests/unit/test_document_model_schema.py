from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


class DocumentModelSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "schemas" / "document-model.schema.json"
        self.validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))

    def test_accepts_minimal_document_model(self) -> None:
        self.assertEqual([], list(self.validator.iter_errors(_valid_model())))

    def test_rejects_unknown_document_type(self) -> None:
        payload = _valid_model()
        payload["document_type"] = "adr"

        self.assertTrue(list(self.validator.iter_errors(payload)))

    def test_rejects_invalid_block_shape(self) -> None:
        payload = _valid_model()
        payload["sections"][0]["blocks"][0]["extra"] = "not allowed"

        self.assertTrue(list(self.validator.iter_errors(payload)))


def _valid_model() -> dict:
    return {
        "schema_version": 1,
        "document_id": "DOC-20260429-decision-brief",
        "document_type": "decision-brief",
        "audience": "human",
        "generated_at": "2026-04-29T00:00:00Z",
        "project_head": "H-test",
        "source": {
            "session_ids": ["S-001"],
            "object_ids": ["DEC-001"],
            "link_ids": ["L-001"],
            "diagnostic_types": ["safety_gates"],
        },
        "title": "Decision Brief",
        "sections": [
            {
                "id": "purpose",
                "title": "Purpose",
                "order": 10,
                "blocks": [{"type": "text", "text": "Current purpose."}],
                "source_object_ids": ["DEC-001"],
                "source_link_ids": ["L-001"],
            }
        ],
        "warnings": [],
        "metadata": {},
    }


if __name__ == "__main__":
    unittest.main()
