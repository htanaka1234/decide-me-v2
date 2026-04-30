from __future__ import annotations

import unittest

from tests.helpers.snapshot_normalization import normalize_json_snapshot, stable_json


class SnapshotNormalizationTests(unittest.TestCase):
    def test_normalize_json_snapshot_drops_only_volatile_keys(self) -> None:
        payload = {
            "generated_at": "2026-04-29T00:00:00Z",
            "project_head": "PH-1",
            "last_event_id": "E-1",
            "tx_id": "T-1",
            "scenario_id": "research_protocol",
            "nested": {
                "tx_id": "T-2",
                "kept": True,
            },
            "items": [
                {
                    "generated_at": "2026-04-29T00:01:00Z",
                    "value": 3,
                }
            ],
        }

        self.assertEqual(
            {
                "items": [{"value": 3}],
                "nested": {"kept": True},
                "scenario_id": "research_protocol",
            },
            normalize_json_snapshot(payload),
        )

    def test_stable_json_renders_sorted_normalized_json(self) -> None:
        self.assertEqual('{\n  "a": 1,\n  "z": 2\n}\n', stable_json({"z": 2, "tx_id": "T-1", "a": 1}))


if __name__ == "__main__":
    unittest.main()
