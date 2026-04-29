from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, RefResolver

from decide_me.projections import default_session_state
from decide_me.validate import StateValidationError, validate_session_state


class SessionStateSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        schema_dir = Path(__file__).resolve().parents[2] / "schemas"
        session_schema = json.loads((schema_dir / "session-state.schema.json").read_text(encoding="utf-8"))
        close_summary_schema = json.loads((schema_dir / "close-summary.schema.json").read_text(encoding="utf-8"))
        resolver = RefResolver.from_schema(
            session_schema,
            store={
                session_schema["$id"]: session_schema,
                close_summary_schema["$id"]: close_summary_schema,
            },
        )
        self.validator = Draft202012Validator(session_schema, resolver=resolver)

    def test_existing_session_state_without_domain_pack_metadata_still_validates(self) -> None:
        payload = default_session_state("S-001", "2026-04-29T00:00:00Z", "Legacy session")

        self.assertEqual([], list(self.validator.iter_errors(payload)))
        validate_session_state(payload)

    def test_session_state_accepts_optional_domain_pack_metadata(self) -> None:
        payload = default_session_state("S-001", "2026-04-29T00:00:00Z", "Research session")
        payload["classification"].update(
            {
                "domain": "data",
                "domain_pack_id": "research",
                "domain_pack_version": "0.1.0",
                "domain_pack_digest": "DP-123456789abc",
                "updated_at": "2026-04-29T00:00:00Z",
            }
        )

        self.assertEqual([], list(self.validator.iter_errors(payload)))
        validate_session_state(payload)

    def test_session_state_rejects_unknown_classification_fields(self) -> None:
        payload = default_session_state("S-001", "2026-04-29T00:00:00Z", "Bad session")
        payload["classification"]["python_hook"] = "decide_me.plugins.research"

        self.assertTrue(list(self.validator.iter_errors(payload)))
        with self.assertRaisesRegex(StateValidationError, "unsupported fields"):
            validate_session_state(payload)

    def test_session_state_rejects_invalid_domain_pack_metadata(self) -> None:
        cases = (
            ("domain_pack_id", "Research", "domain_pack_id"),
            ("domain_pack_digest", "DP-nothex", "domain_pack_digest"),
        )
        for key, value, message in cases:
            with self.subTest(key=key):
                payload = default_session_state("S-001", "2026-04-29T00:00:00Z", "Bad session")
                payload["classification"].update(
                    {
                        "domain_pack_id": "research",
                        "domain_pack_version": "0.1.0",
                        "domain_pack_digest": "DP-123456789abc",
                    }
                )
                payload["classification"][key] = value

                self.assertTrue(list(self.validator.iter_errors(payload)))
                with self.assertRaisesRegex(StateValidationError, message):
                    validate_session_state(payload)

    def test_session_state_rejects_partial_domain_pack_metadata(self) -> None:
        cases = (
            {"domain_pack_id": "research"},
            {"domain_pack_digest": "DP-123456789abc"},
            {"domain_pack_id": "research", "domain_pack_version": "0.1.0"},
        )
        for metadata in cases:
            with self.subTest(metadata=metadata):
                payload = default_session_state("S-001", "2026-04-29T00:00:00Z", "Bad session")
                payload["classification"].update(metadata)

                self.assertTrue(list(self.validator.iter_errors(payload)))
                with self.assertRaisesRegex(StateValidationError, "incomplete domain pack metadata"):
                    validate_session_state(payload)


if __name__ == "__main__":
    unittest.main()
