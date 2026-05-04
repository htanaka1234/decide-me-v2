from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from decide_me.lifecycle import create_session
from decide_me.store import bootstrap_runtime, read_event_log, runtime_paths, transact
from decide_me.validate import StateValidationError
from tests.helpers.typed_metadata import risk_metadata


class EventMetadataValidationIntegrationTests(unittest.TestCase):
    def test_transact_rejects_invalid_metadata_patch_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ai_dir = Path(tmp)
            bootstrap_runtime(
                ai_dir,
                project_name="Demo",
                objective="Validate event metadata.",
                current_milestone="PR6",
            )
            session_id = create_session(str(ai_dir), "metadata validation")["session"]["id"]
            transact(
                ai_dir,
                lambda _bundle: [
                    {
                        "session_id": session_id,
                        "event_type": "object_recorded",
                        "payload": {"object": _object("RISK-001", "E-risk-1", "risk", risk_metadata())},
                    }
                ],
            )
            before_events = read_event_log(runtime_paths(ai_dir))

            with self.assertRaisesRegex(StateValidationError, "risk object RISK-001.metadata.risk_tier"):
                transact(
                    ai_dir,
                    lambda _bundle: [
                        {
                            "session_id": session_id,
                            "event_type": "object_updated",
                            "payload": {
                                "object_id": "RISK-001",
                                "patch": {"metadata": {"risk_tier": "severe"}},
                            },
                        }
                    ],
                )

            self.assertEqual(before_events, read_event_log(runtime_paths(ai_dir)))


def _object(object_id: str, event_id: str, object_type: str, metadata: dict) -> dict:
    return {
        "id": object_id,
        "type": object_type,
        "title": object_id,
        "body": "Validate typed metadata.",
        "status": "active",
        "created_at": "2026-04-23T12:00:00Z",
        "updated_at": None,
        "source_event_ids": [event_id],
        "metadata": metadata,
    }


if __name__ == "__main__":
    unittest.main()
